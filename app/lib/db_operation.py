import sqlite3
from sqlite3 import Error
import os
from app.lib.utils import GetEnv, format_startlist, get_event_data_all
from app.lib.db_func import *
from flask import request 
import json


def delete_events(directory_path, event=None):
    if event != None:
        os.remove(directory_path+event+".sqlite")
        return
    
    files = os.listdir(directory_path)
    for file in files:
        file_path = os.path.join(directory_path, file)
        
        if os.path.isfile(file_path):
            os.remove(file_path)



def full_db_reload(add_intel_sort=False, sync=False, Event=None):
    from app.models import ActiveEvents, EventOrder, EventType
    from app.lib.utils import insert_orbits_data
    from app import db
    from sqlalchemy import func


    g_config = GetEnv()

    if g_config["msport_tm"] == False:
        insert_orbits_data()

    delete_events(g_config["db_location"], event=Event)
    
    if Event != None:
        db_data, driver_db_data = map_database_files(g_config, Event=Event)
        
        for a in db_data:
            installed_heats = int(ActiveEvents.query.filter(ActiveEvents.event_file==Event).count())
            gotten_heats = int(a["HEATS"])
            hightest_heat = (
                ActiveEvents.query.filter(ActiveEvents.event_name == a["TITLE1"] + " " + a["TITLE2"]).order_by(ActiveEvents.sort_order.desc()).first()
            )

            max_sort_order_subquery = ActiveEvents.query.with_entities(func.max(ActiveEvents.sort_order).label("max_sort_order")).subquery()

            entry_range = ActiveEvents.query.filter(
                ActiveEvents.sort_order.between(hightest_heat.sort_order, max_sort_order_subquery.c.max_sort_order)
            ).all()


            if gotten_heats > installed_heats:
                sort_oder_addition = (gotten_heats - installed_heats)

                entry_range = ActiveEvents.query.filter(
                    ActiveEvents.sort_order.between((hightest_heat.sort_order)+1, max_sort_order_subquery.c.max_sort_order)
                ).all()

                for entry in entry_range:
                    entry.sort_order += sort_oder_addition 

                db.session.commit()

                for k, b in enumerate(range(installed_heats, gotten_heats)):
                    sort_value = hightest_heat.sort_order + (k + 1)
                    event_entry = ActiveEvents(event_name=(a["TITLE1"] + " " + a["TITLE2"]), run=(b + 1), sort_order=sort_value, event_file=a["db_file"], mode=a["MODE"])
                    db.session.add(event_entry)

                db.session.commit()

            elif gotten_heats < installed_heats:
                sort_order_sub = (installed_heats - gotten_heats)
                
                for b in range(gotten_heats, installed_heats):
                    ActiveEvents.query.filter(
                        ActiveEvents.event_name == (a["TITLE1"] + " " + a["TITLE2"]),
                        ActiveEvents.run == b + 1
                    ).delete()

                    print("remove:" )

                entry_range = ActiveEvents.query.filter(
                    ActiveEvents.sort_order.between((hightest_heat.sort_order)+1, max_sort_order_subquery.c.max_sort_order)
                ).all()

                for entry in entry_range:
                    entry.sort_order -= sort_order_sub 

                db.session.commit()
    else:

        db_data, driver_db_data = map_database_files(g_config)
        ActiveEvents.query.delete()
        count = 0

        #I moved this indise the if statement. 
        for a in db_data:
            for b in range(1, (int(a['HEATS']) + 1)):
                count += 1
                
                event_entry = ActiveEvents(event_name=(a["TITLE1"] + " " + a["TITLE2"]), run=b, sort_order=count, event_file=a["db_file"], mode=a["MODE"])
                db.session.add(event_entry)

        db.session.commit()

    if add_intel_sort:


        EventType.query.delete()
        EventOrder.query.delete()
        event_types = []
        for a in db_data:
            if a["TITLE2"].split(" ")[-1] not in event_types:
                event_types.append(a["TITLE2"].split(" ")[-1])
        
        event_names = []
        for a in db_data:
            if a["TITLE2"].split(' - ')[0] not in event_names:
                event_names.append(a["TITLE2"].split(' - ')[0])

        event_type_db_lst = []
        for k,a in enumerate(event_types):
            k += 1
            event_type = EventType(order=k, name=a, finish_heat=False)
            event_type_db_lst.append(event_type)
        
        db.session.add_all(event_type_db_lst)
        db.session.commit()

        event_name_db_lst = []
        for k,a in enumerate(event_names):
            k += 1
            event_order = EventOrder(order=k, name=a)
            event_name_db_lst.append(event_order)
        
        db.session.add_all(event_name_db_lst)
        db.session.commit()

    init_database(db_data, driver_db_data, g_config)
    insert_start_list(db_data, g_config, init_mode=False)
    insert_driver_stats(db_data, g_config)


def reload_event(db, heat):
    g_config = GetEnv()
    db_init = [{'db_file':db,'SPESIFIC_HEAT':heat}]
    insert_driver_stats(db_init, g_config, init_mode=False, exclude_lst=True)

def update_event(db, heat):
    g_config = GetEnv()
    insert_driver_stats(db, heat, g_config, init_mode=False, exclude_lst=True)

def update_active_event_stats(Emit=True):
    from flask import current_app
    from app.lib.db_func import clear_driver_table
    
    g_config = GetEnv()

    active_event = get_active_event()
    
    if g_config["msport_tm"]:
        update_active_event(g_config)
    else:
        if active_event[0]["db_file"] != 'Event000':
            clear_driver_table(active_event, g_config)
    
    change_active_driver = False



    if current_app.config['current_event'] != active_event:
        current_app.config['current_event'] = active_event
        change_active_driver = True
    
    #print(event, heat)
    #db_data, driver_db_data = map_database_files(g_config, "Event008")
    #print(db_data, driver_db_data)
    try:
        if not g_config["msport_tm"]:
            #This will updated the list of driver in the "drivers" table, needed to do this to make orbits happy
            update_drivers = True
        else:
            update_drivers = False
        insert_start_list(active_event, g_config, init_mode=False, set_active_driver=change_active_driver, update_drivers_table=update_drivers)
        insert_driver_stats(active_event, g_config, init_mode=False, exclude_lst=True)   
        
    except Exception as Error:
        print(Error)

    return "data"


def update_active_event_startlist():
    g_config = GetEnv()
    active_event = get_active_event()

    insert_driver_stats(active_event, g_config, init_mode=False, exclude_lst=True)



def get_active_startlist():

    g_config = GetEnv()
    event = get_active_event()
    event_db_file = (g_config["db_location"]+event[0]["db_file"]+".sqlite")
    event[0]["db_file"] = event_db_file
    try:
        data = json.dumps(format_startlist(event))
    except Exception as err:
        print("Could not build event JSON:", event)
        print(err)
        return
    return data


def get_active_startlist_w_timedate(upcoming=False, event_wl=None, event_comb=None, heat=None, event=None):
    from app.lib.utils import get_event_data
    from app.models import ActiveDrivers, Session_Race_Records, ActiveEvents

    if event == None:
        active_drivers_row = ActiveDrivers.query.get(1)
        d1 = active_drivers_row.D1 if active_drivers_row else None
        d2 = active_drivers_row.D2 if active_drivers_row else None
        event_name = active_drivers_row.Event
        heat = active_drivers_row.Heat

        if upcoming:
            current_ae = (
                ActiveEvents.query
                .filter(ActiveEvents.event_name == event_name, ActiveEvents.run == heat)
                .first()
            )
            if current_ae:
                next_ae = (
                    ActiveEvents.query
                    .filter(ActiveEvents.sort_order > current_ae.sort_order, ActiveEvents.enabled == True)
                    .order_by(ActiveEvents.sort_order)
                    .first()
                )
                if next_ae:
                    event_name = next_ae.event_name
                    heat = next_ae.run
                    d1 = 9999
                    d2 = 9999
                else:
                    return [{"race_config": {}}]

        records = (
            Session_Race_Records.query
            .filter(Session_Race_Records.title_2 == event_name, Session_Race_Records.heat == heat)
            .all()
        )
        if not records:
            return []

    else:
        d1 = 9999
        d2 = 9999
        try:
            heat = int(heat)
        except (TypeError, ValueError):
            pass
        records = (
            Session_Race_Records.query
            .filter(Session_Race_Records.title_2 == event, Session_Race_Records.heat == heat)
            .all()
        )
    if not records:
        return []
    records.sort(key=lambda r: (r.data.get("start_pos") or 0))
    first = records[0].data
    module = first.get("module", "0")
    if int(module) == 0:
        d2 = 9999
    result = [{
        "race_config": {
            "MODE":    int(module),
            "HEATS":   first.get("heats", len(records)),
            "HEAT":    first.get("heat", 1),
            "TITLE_1": first.get("title_1", ""),
            "TITLE_2": first.get("title_2", ""),
            "DATE":    "",
            "CROSS":   GetEnv().get("cross", False),
        }
    }]

    step = 2 if module in ("2", "3") else 1
    for i in range(0, len(records), step):
        group = records[i:i + step]
        drivers = []
        for rec in group:
            d = rec.data or {}
            cid = rec.cid
            ti = {
                "INTER_1":    d.get("inter_1", 0),
                "INTER_2":    d.get("inter_2", 0),
                "SPEED":      d.get("speed", 0),
                "PENELTY":    d.get("penalty", 0),
                "FINISHTIME": d.get("finishtime", 0),
                "REACTION":   d.get("reaction", 0),
            }
            drivers.append({
                "id":         cid,
                "first_name": d.get("first_name"),
                "last_name":  d.get("last_name"),
                "club":       d.get("club"),
                "vehicle":    d.get("snowmobile"),
                "active":     cid in (d1, d2),
                "time_info":  ti,
            })

        if len(drivers) == 2:
            a, b = drivers[0], drivers[1]
            ft_a = a["time_info"]["FINISHTIME"]
            ft_b = b["time_info"]["FINISHTIME"]
            pen_a = a["time_info"]["PENELTY"]
            pen_b = b["time_info"]["PENELTY"]
            if pen_a and not pen_b:
                a["status"] = 2; b["status"] = 1
            elif pen_b and not pen_a:
                a["status"] = 1; b["status"] = 2
            elif ft_a and ft_b and not pen_a and not pen_b:
                if ft_a < ft_b:
                    a["status"] = 1; b["status"] = 2
                else:
                    a["status"] = 2; b["status"] = 1

        result.append({"race_id": (i // step) + 1, "drivers": drivers})

    return result

def get_specific_event_data(event_filter=None):

    g_config = GetEnv()
    if event_filter != None:
        event = event_filter
    else:
        event = get_active_event()
    
    event_db_file = (g_config["db_location"]+event[0]["db_file"]+".sqlite")
    event[0]["db_file"] = event_db_file
    data = get_event_data_all(event)
    #data = json.dumps(format_startlist(event, include_timedata=True))
    return data

def get_active_event():
    from app.models import ActiveDrivers
    from app import db


    data = ActiveDrivers.query.get(1)
    
    if data is None:
        g_config = GetEnv()
        update_active_event(g_config)
        data = ActiveDrivers.query.get(1)

    event = str(data.Event).zfill(3)

    return [{"db_file": "Event"+str(event), "SPESIFIC_HEAT": str(data.Heat), "event_id": str(data.Event_id)}]
    
def update_active_event(g_conf):
    from app.models import ActiveDrivers
    from app import db

    event_dir = g_conf["event_dir"]


    try:
        with sqlite3.connect(event_dir+"Online.scdb") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT C_VALUE FROM TPARAMETERS WHERE C_PARAM='EVENT' OR C_PARAM='HEAT';")
            rows = cursor.fetchall()

        data = ActiveDrivers.query.get(1)
        data.Event = rows[0][0]
        data.Heat = rows[1][0]
        db.session.commit()

    except:
        print("Could not access event files")

def get_active_event_name():
    event = get_active_event()
    db_location = GetEnv()["db_location"]
    heat = event[0]["SPESIFIC_HEAT"]
    with sqlite3.connect(db_location + event[0]["db_file"]+".sqlite") as conn:
        cursor = conn.cursor()
        event_data = cursor.execute("SELECT MODE, RUNS, TITLE1, TITLE2, DATE FROM db_index;").fetchall()

    event_data = {"title_1":event_data[0][2], "title_2":event_data[0][3], "heat":str(heat) + "/" + str(event_data[0][1])}
    return event_data

