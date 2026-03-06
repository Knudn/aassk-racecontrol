import sqlite3
from sqlite3 import Error
import random
import os
from app.lib.utils import GetEnv
from typing import List, Dict, Union, Tuple
from datetime import datetime, timedelta
import traceback
import xml.etree.ElementTree as ET


def clear_driver_table(active_event, g_config):

    db_path = g_config["event_dir"]+active_event[0]["db_file"]+".scdb"
    db_location = g_config["db_location"]
    local_event_db = db_location+active_event[0]["db_file"]+".sqlite"
    driver_entries = []
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT C_NUM, C_FIRST_NAME, C_LAST_NAME, C_CLUB, C_TEAM FROM TCOMPETITORS;")
        driver_rows = cursor.fetchall()


    for h in driver_rows:
        driver_entries.append((h[0], h[1], h[2], h[3], h[4]))
    
    with sqlite3.connect(local_event_db) as conn:
        cursor = conn.cursor()
        sql = "INSERT OR IGNORE INTO drivers (CID, FIRST_NAME, LAST_NAME, CLUB, SNOWMOBILE) VALUES (?, ?, ?, ?, ?);"
        cursor.execute(f'DELETE FROM drivers;')
        cursor.executemany(sql, driver_entries)


def timevalue_convert(dateint):
    dateint = 4362
    base_date = datetime(1900, 1, 1)
    actual_date = base_date + timedelta(days=dateint - 2)
    return actual_date.strftime("%Y-%m-%d")
    

def insert_orbits_data(active_only=False, event_id=None, calculate_points=False, ignore_locked=False, full_sync=False):
    from app.models import Session_Race_Records, ActiveEvents, StandingConfig
    import json
    from sqlalchemy import func
    from app import db as my_db
    from app.lib.utils import calculate_standing
    from app.lib.db_operation import get_active_event
    


    global_config = GetEnv()

    wl_bool = bool(global_config["wl_bool"])
    wl_title = bool(global_config["wl_title"])
    event_dir = global_config["event_dir"]
    race_mode = global_config["race_type"]

    mix_classes = StandingConfig.query.first().mix_classes

    with sqlite3.connect(event_dir+'/race_state.db') as conn:
        
        cursor = conn.cursor()
        if active_only == True:
            current_event_id = get_active_event()[0]["event_id"]
            cursor.execute("select cid, run_name, heat, active_event, event_id, data from race_entries where event_id='{0}';".format(current_event_id))
        elif event_id != None:
            cursor.execute("select cid, run_name, heat, active_event, event_id, data from race_entries where event_id='{0}';".format(event_id))
        elif full_sync == True:
            cursor.execute("select cid, run_name, heat, active_event, event_id, data from race_entries;")        
        
        entries = cursor.fetchall()

        cursor.execute("select run_name, heat, data, event_checksum from schedule_entries;")
        active_events = cursor.fetchall()

    # Make sure Active Event meta is inserted in the next insert
    current_meta_config_q = ActiveEvents.query.all()
    backup_event_lst = {}
    for current_meta_config in current_meta_config_q:
        finish_laps = current_meta_config.finish_laps
        finish_time = current_meta_config.finish_time
        finish_criteria = current_meta_config.finish_criteria
        event_checksum = current_meta_config.event_checksum
        override_finish = current_meta_config.override_finish
        finished = current_meta_config.finished

        backup_event_lst[event_checksum] = [finish_criteria, finish_time, finish_laps, override_finish, finished]

    #Clear active events
    ActiveEvents.query.delete()
    my_db.session.commit() 

    for b in active_events:

        event_dict = json.loads(b[2])
        event_name = b[0]
        heat = b[1]
        event_checksum = b[3]
        sort_order = event_dict["sort_order"]
        event_type = event_dict["event_type"]
        entry = ActiveEvents(event_name=event_name, run=heat, sort_order=sort_order, mode=race_mode, event_type=event_type)
        if event_checksum in backup_event_lst:
            entry.finish_criteria = backup_event_lst[event_checksum][0]
            entry.finish_laps = backup_event_lst[event_checksum][2]
            entry.finish_time = backup_event_lst[event_checksum][1]
            entry.override_finish = backup_event_lst[event_checksum][3]
            entry.finished = backup_event_lst[event_checksum][4]


        my_db.session.add(entry)
    my_db.session.commit()

    locked_lst = []

    if not ignore_locked:
        locked_entries = Session_Race_Records.query.filter(Session_Race_Records.locked == True).all()
        for entry in locked_entries:
            locked_lst.append(str(entry.cid)+str(entry.title_2)+str(entry.heat))

    if active_only:
        if entries == []:
            return "NO ACTIVE EVENT!" 

        Session_Race_Records.query.filter(Session_Race_Records.event_id == current_event_id, Session_Race_Records.locked == False).delete()
        
        groups = {}
        score_dict = {}

        ex_dict = json.loads(entries[0][5])
        event_id = ex_dict["event_id"]
        finish_state = ex_dict["finished"]
        active_event = ActiveEvents.query.filter(ActiveEvents.event_checksum==event_id).first()
        
        if bool(active_event.finished) != bool(finish_state):
             active_event.finished = bool(finish_state)
             my_db.session.commit()

        for a in entries:
            if bool(json.loads(a[5])["multi_class"]) and mix_classes == False:
                event_id_ent = a[4] + "_" + json.loads(a[5])["class"]
                if event_id_ent not in groups:
                    groups[event_id_ent] = []
                groups[event_id_ent].append(a)
            else:
                event_id = a[4]

                if event_id not in groups:
                    groups[event_id] = []
                groups[event_id].append(a)
        
        for a in groups:
            standings = calculate_standing(groups[a])
            standings_dict = {cid: pos for cid, pos in standings}
            score_dict[a] = standings_dict

        for a in entries:
            cid = a[0]
            run_name = a[1]
            heat = a[2]
            event_id = a[4]
            active_event = bool(a[3])
            data = json.loads(a[5])

            if backup_event_lst.get(event_id, [None, None, 0])[2] == 1:
                totaltime = data.get("totaltime", "")
                data["last_lap_time"] = totaltime
                data["best_time"] = totaltime

            if bool(data["multi_class"]) and mix_classes == False:
                event_id_ent = event_id + "_" + data["class"]
            else:
                event_id_ent = event_id

            locked_str = str(cid)+str(run_name)+str(heat)

            if active_event == False:
                continue

            if locked_str in locked_lst:
                continue

            data["internal_standing"] = score_dict[event_id_ent][cid][0]
            data["points"] = score_dict[event_id_ent][cid][1]

            entry = Session_Race_Records(cid=cid, title_1=data.get("title_1", run_name), title_2=run_name, heat=int(heat), active_event=active_event, event_id=event_id, data=data)
            my_db.session.add(entry)

        my_db.session.commit()

    elif event_id != None:
        Session_Race_Records.query.filter(Session_Race_Records.event_id == event_id).delete()
        groups = {}
        score_dict = {}
        for a in entries:
            if bool(json.loads(a[5])["multi_class"]) and mix_classes == False:
                event_id_ent = a[4] + "_" + json.loads(a[5])["class"]
                if event_id_ent not in groups:
                    groups[event_id_ent] = []
                groups[event_id_ent].append(a)
            else:
                event_id = a[4]

                if event_id not in groups:
                    groups[event_id] = []
                groups[event_id].append(a)
        
        for a in groups:
            standings = calculate_standing(groups[a])
            standings_dict = {cid: pos for cid, pos in standings}
            score_dict[a] = standings_dict

        for a in entries:
            cid = a[0]
            run_name = a[1]
            heat = a[2]
            event_id = a[4]
            active_event = bool(a[3])
            data = json.loads(a[5])

            if backup_event_lst.get(event_id, [None, None, 0])[2] == 1:
                totaltime = data.get("totaltime", "")
                data["last_lap_time"] = totaltime
                data["best_time"] = totaltime

            if bool(data["multi_class"]):
                event_id_ent = event_id + "_" + data["class"]
            else:
                event_id_ent = event_id

            locked_str = str(cid)+str(run_name)+str(heat)

            if active_event == False:
                continue

            if locked_str in locked_lst:
                continue

            data["internal_standing"] = score_dict[event_id_ent][cid][0]
            data["points"] = score_dict[event_id_ent][cid][1]

            entry = Session_Race_Records(cid=cid, title_1=data.get("title_1", run_name), title_2=run_name, heat=int(heat), active_event=active_event, event_id=event_id, data=data)
            my_db.session.add(entry)
        my_db.session.commit()

    else:
        from app.models import ActiveDrivers
        Session_Race_Records.query.filter(Session_Race_Records.locked == False).delete()
        my_db.session.commit()
        

        
        grouped = {}
        standings_dict_group = {}
        found_active_event = False

        for t in entries:
            event_id = t[4]

            ex_dict = json.loads(t[5])

            finish_state = ex_dict["finished"]
            active_event = ActiveEvents.query.filter(ActiveEvents.event_checksum==event_id).first()
            
            if bool(active_event.finished) != bool(finish_state):
                active_event.finished = bool(finish_state)
                my_db.session.commit()
            if bool(json.loads(t[5])["multi_class"]) and mix_classes == False:
                event_id_ent = event_id + "_" +json.loads(t[5])["class"]
            else:
                event_id_ent = event_id

            if event_id_ent not in grouped:
                grouped[event_id_ent] = []
            grouped[event_id_ent].append(t)
        


        
        for a in grouped:
            standings = calculate_standing(grouped[a])

            standings_dict = {cid: pos for cid, pos in standings}
            standings_dict_group[a] = standings_dict

        for a in entries:
            cid = a[0]
            
            run_name = a[1]
            heat = a[2]
            event_id = a[4]
            active_event = bool(a[3])
            if active_event and found_active_event == False:
               current_active_state = ActiveDrivers.query.first()
               current_active_state.Event_id = event_id

               my_db.session.commit()
               found_active_event = True
            data = json.loads(a[5])

            if backup_event_lst.get(event_id, [None, None, 0])[2] == 1:
                totaltime = data.get("totaltime", "")
                data["last_lap_time"] = totaltime
                data["best_time"] = totaltime

            locked_str = str(cid)+str(run_name)+str(heat)

            if locked_str in locked_lst:
                continue
            if data["multi_class"] and mix_classes == False:
                event_id_ent = event_id + "_" + data["class"]
            else:
                event_id_ent = event_id
            if cid in standings_dict_group[event_id_ent]:
                data["internal_standing"] = standings_dict_group[event_id_ent][cid][0]
                data["points"] = standings_dict_group[event_id_ent][cid][1]

            entry = Session_Race_Records(cid=cid, title_1=data.get("title_1", run_name), title_2=run_name, event_id=event_id, heat=int(heat), active_event=active_event, data=data)
            my_db.session.add(entry)

        my_db.session.commit()

def msport_get_active_event():

    g_config  = GetEnv()
    event_dir = g_config["event_dir"]

    def _snapshot(src):
        src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=5)
        mem = sqlite3.connect(":memory:")
        src_conn.backup(mem, pages=-1)
        src_conn.close()
        return mem
    
    online_path = os.path.join(event_dir, "Online.scdb")
    if os.path.exists(online_path):
        conn = _snapshot(online_path)
        params = {r[0]: r[1] for r in conn.cursor().execute(
            "SELECT C_PARAM, C_VALUE FROM TPARAMETERS WHERE C_PARAM IN ('EVENT', 'HEAT');"
        ).fetchall()}
        conn.close()
        event_number = params.get("EVENT")
        active_heat  = params.get("HEAT")

    return event_number, active_heat

def insert_msports_data(active=False, event_number=None, full_sync=False, lookup_active=False):
    from app.models import Session_Race_Records, ActiveEvents, ActiveDrivers
    from app import db as my_db
    from app.lib.utils import GetEnv, calculate_standing_msport
    import zlib


    def _snapshot(src):
        src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=5)
        mem = sqlite3.connect(":memory:")
        src_conn.backup(mem, pages=-1)
        src_conn.close()
        return mem

    g_config  = GetEnv()
    wl_bool   = bool(g_config["wl_bool"])
    wl_title  = g_config["wl_title"]
    race_type = g_config["race_type"]
    event_dir = g_config["event_dir"]

    active_heat = None

    if lookup_active:
        event_number, heat = msport_get_active_event()
        active_event_state = ActiveDrivers.query.first()
        active_event_state.Heat = heat
        active_event_state.Event_id = event_number.zfill(3)
        title_2 = Session_Race_Records.query.filter(Session_Race_Records.event_id == event_number.zfill(3)).first().title_2
        active_event_state.Event = title_2

        my_db.session.commit()

    if active:
        active_event = ActiveDrivers.query.first().Event_id
        paths = [os.path.join(event_dir, f"Event{int(active_event):03d}.scdb")]
    elif full_sync:
        paths = sorted([
            os.path.join(event_dir, f)
            for f in os.listdir(event_dir)
            if f.endswith(".scdb") and "ex" not in f.lower() and "online" not in f.lower()
        ])
    
        Session_Race_Records.query.filter(Session_Race_Records.locked == False).delete()
        my_db.session.commit()
    elif event_number is not None:
        candidate = os.path.join(event_dir, f"Event{int(event_number):03d}.scdb")
        paths = [candidate] if os.path.exists(candidate) else []
    else:
        return

    kvali_event_dict = {}  # {title2: driver_count} for module "2" qualifying events

    active_events_dict = {}

    for path in paths:
        ex_path = path.replace(".scdb", "Ex.scdb")
        if not os.path.exists(ex_path):
            continue

        conn, ex_conn = _snapshot(path), _snapshot(ex_path)
        try:
            cur, ex_cur = conn.cursor(), ex_conn.cursor()

            # Alphabetical PK order: DATE, HEAT_NUMBER, MODULE, TITLE1, TITLE2
            rows = cur.execute(
                "SELECT C_VALUE FROM TPARAMETERS"
                " WHERE C_PARAM='DATE' OR C_PARAM='MODULE'"
                " OR C_PARAM='TITLE1' OR C_PARAM='TITLE2' OR C_PARAM='HEAT_NUMBER';"
            ).fetchall()
            
            if len(rows) < 5:
                continue

            _, heat_number, module, title1, title2 = [r[0] for r in rows]
            heat_number = int(heat_number)

            if wl_bool and wl_title and wl_title.upper() not in (title1 + " " + title2).upper():
                continue
            title_2_col = f"{title1} {title2}"
            
            p_event_id = path.split("/")[-1].replace("Event","").replace(".scdb","")
            active_events_dict[p_event_id] = {"event_name":title1 + " " + title2, "title2":title2, "mode":module, "event_file":p_event_id, "heats":[]}

            try:
                file_event_id = str(int(os.path.basename(path).replace("Event", "").replace(".scdb", "")))
            except ValueError:
                file_event_id = None

            competitors = {
                r[0]: {"first_name": r[1], "last_name": r[2], "club": r[3], "snowmobile": r[4]}
                for r in cur.execute(
                    "SELECT C_NUM, C_FIRST_NAME, C_LAST_NAME, C_CLUB, C_TEAM FROM TCOMPETITORS;"
                ).fetchall()
            }

            for heat in range(1, heat_number + 1):
                if heat not in active_events_dict[p_event_id]["heats"]:
                    active_events_dict[p_event_id]["heats"].append(heat)
                
                if module == "0":
                    sl_table, time_table = f"TSTARTLIST_HEAT{heat}", f"TTIMEINFOS_HEAT{heat}"
                elif module == "2":
                    sl_table, time_table = f"TSTARTLIST_PARQ2_HEAT{heat}", f"TTIMEINFOS_HEAT{heat}"
                elif module == "3":
                    inv        = (heat_number - heat) + 1
                    sl_table   = f"TSTARTLIST_PARF_HEAT{inv}"
                    time_table = f"TTIMEINFOS_PARF_HEAT{inv}_RUN1"
                else:
                    continue

                #event_id  = f"{zlib.crc32(f'{title_2_col} {heat}'.encode()):08x}"
                event_id  = file_event_id.zfill(3)
                is_active = bool(
                    file_event_id
                    and str(file_event_id) == str(event_number)
                    and str(heat) == str(active_heat)
                )

                Session_Race_Records.query.filter(
                    Session_Race_Records.event_id == event_id,
                    Session_Race_Records.heat     == heat,
                    Session_Race_Records.locked   == False
                ).delete()

                try:
                    startlist = {r[0]: r[1] for r in ex_cur.execute(f"SELECT C_NUM, C_START FROM {sl_table};").fetchall()}
                except Exception:
                    startlist = {}

                if module == "2" and startlist:
                    kvali_event_dict[title2] = max(kvali_event_dict.get(title2, 0), len(startlist))

                try:
                    timing = {
                        r[0]: {"inter_1": r[1], "inter_2": r[2], "inter_3": r[3],
                               "speed": r[4], "penalty": r[5], "finishtime": r[6], "reaction": r[7]}
                        for r in ex_cur.execute(
                            f"SELECT C_NUM, C_INTER1, C_INTER2, C_INTER3, C_SPEED1, C_STATUS, C_TIME, C_DATA2"
                            f" FROM {time_table};"
                        ).fetchall()
                    }
                except Exception:
                    timing = {}


                for cid, start_pos in startlist.items():
                    d, t = competitors.get(cid, {}), timing.get(cid, {})
                    data = {
                        "cid":        cid,
                        "first_name": d.get("first_name"),
                        "last_name":  d.get("last_name"),
                        "title_1":    title1,
                        "title_2":    title2,
                        "heat":       heat,
                        "heats":      heat_number,
                        "finishtime": t.get("finishtime", 0),
                        "snowmobile": d.get("snowmobile"),
                        "penalty":    t.get("penalty", 0),
                        "reaction":   t.get("reaction", 0),
                        "inter_1":    t.get("inter_1", 0),
                        "inter_2":    t.get("inter_2", 0),
                        "inter_3":    t.get("inter_3", 0),
                        "speed":      t.get("speed", 0),
                        "club":       d.get("club"),
                        "start_pos":  start_pos,
                        "laps":       0,
                        "points":     0,
                        "race_type":  race_type,
                        "module":     module,
                    }
                    my_db.session.add(Session_Race_Records(
                        event_id=event_id, title_2=title2, title_1=title1,
                        cid=cid, active_event=is_active, heat=heat, data=data
                    ))

                my_db.session.commit()

            # Recalculate standings for this event across all heats
            event_records = Session_Race_Records.query.filter(
                Session_Race_Records.title_2 == title2
            ).all()
            if event_records:
                standing_result = calculate_standing_msport(
                    [r.data for r in event_records if r.data]
                )
                standing_map = {
                    row["cid"]: (row["internal_standing"], row["points"])
                    for row in standing_result["results"]
                }
                for rec in event_records:
                    cid = rec.cid
                    if cid in standing_map and not rec.locked:
                        standing, points = standing_map[cid]
                        rec.data = {**rec.data, "internal_standing": standing, "points": points}
                my_db.session.commit()

        finally:
            conn.close()
            ex_conn.close()

    if full_sync:
        current_meta_config_q = ActiveEvents.query.all()
        backup_event_lst = {}
        for current_meta_config in current_meta_config_q:
            finish_laps = current_meta_config.finish_laps
            finish_time = current_meta_config.finish_time
            finish_criteria = current_meta_config.finish_criteria
            event_checksum = current_meta_config.event_checksum
            override_finish = current_meta_config.override_finish
            finished = current_meta_config.finished
            backup_event_lst[event_checksum] = [finish_criteria, finish_time, finish_laps, override_finish, finished]
        



        #Clear active events
        ActiveEvents.query.delete()
        my_db.session.commit() 

        k = 1

        for a in active_events_dict:
            event_id = a
            event_name = active_events_dict[a]["event_name"]
            mode = active_events_dict[a]["mode"]
            title_2 = active_events_dict[a]["title2"]
            for g in active_events_dict[a]["heats"]:
                run = g
                event_checksum = f"{zlib.crc32(f'{title_2} {g}'.encode()):08x}"
                entry = ActiveEvents(event_name=title_2, event_file=event_id, run=run, event_checksum=event_checksum, mode=mode, sort_order=k)
                k += 1
                if event_checksum in backup_event_lst:
                    entry.finish_criteria = backup_event_lst[event_checksum][0]
                    entry.finish_laps = backup_event_lst[event_checksum][2]
                    entry.finish_time = backup_event_lst[event_checksum][1]
                    entry.override_finish = backup_event_lst[event_checksum][3]
                    entry.finished = backup_event_lst[event_checksum][4]
                my_db.session.add(entry)
        my_db.session.commit() 




    if kvali_event_dict and full_sync:
        calculate_kvali_nr(kvali_event_dict)

def calculate_kvali_nr(event_dict):
    from app.models import EventKvaliRate
    from app import db as my_db

    g_config = GetEnv()

    try:
        # Wipe and rebuild the table each time
        my_db.session.query(EventKvaliRate).delete()
        
        for count, (event, value) in enumerate(event_dict.items(), start=1):
            if not g_config["msport_tm"]:
                kvalinr = 16
            elif int(g_config["race_type"]) == 3:
                kvalinr = 10
            else:
                kvalinr = 16 if value >= 16 else 8 if value >= 8 else 4 if value >= 4 else 2 if value >= 2 else 1 if value >= 1 else 0

            record = EventKvaliRate(id=count, event=event, kvalinr=kvalinr)
            my_db.session.add(record)

        my_db.session.commit()
        print("All records inserted successfully")

    except Exception as e:
        my_db.session.rollback()
        raise e

    print("All records inserted successfully")
        

