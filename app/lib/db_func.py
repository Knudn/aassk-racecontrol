import sqlite3
from sqlite3 import Error
import random
import os
from app.lib.utils import GetEnv
from typing import List, Dict, Union, Tuple
from datetime import datetime, timedelta
import traceback


def timevalue_convert(dateint):

    base_date = datetime(1900, 1, 1)
    actual_date = base_date + timedelta(days=dateint - 2)
    return actual_date.strftime("%Y-%m-%d")

def map_database_files(global_config, Event=None, event_only=False):
    
    db_data = []
    driver_db_data = {}

    print(global_config)

    event_dir = global_config["event_dir"]
    wh_check = global_config["wl_bool"]
    wh_title = global_config["wl_title"]
    cross_check = global_config["cross"]
    cross_title = global_config["wl_cross_title"]
    exclude_title = global_config["exclude_title"]


    if Event != None:
        events = [Event+".scdb"]
    else:
        events = os.listdir(event_dir)

    if event_only == True:
        tmp_event_list = []

    #This for loop will enumerate a folder to find a bunch of database files

    for filename in events:
        f = os.path.join(event_dir, filename)
        # checking if it is a file
        if os.path.isfile(f):
            if "ex.scdb" not in f.capitalize() and "online" not in f.capitalize():
                with sqlite3.connect(f) as conn:
                    

                    cursor = conn.cursor()
                    cursor.execute("SELECT C_VALUE FROM TPARAMETERS WHERE C_PARAM='DATE' OR C_PARAM='MODULE' OR C_PARAM='TITLE1' OR C_PARAM='TITLE2' OR C_PARAM='HEAT_NUMBER';")
                    rows = cursor.fetchall()
                    if len(rows) <= 4:
                        continue
                    elif rows[3][0] == "COMPETITORS LIST":
                        continue
                    
                    cursor.execute("SELECT C_NUM, C_FIRST_NAME, C_LAST_NAME, C_CLUB, C_TEAM FROM TCOMPETITORS;")
                    driver_rows = cursor.fetchall()
                    if len(rows) >= 4:
                        if exclude_title.upper() in str(rows[3][0] + " " + rows[4][0]).upper() and exclude_title != "":
                            continue
                        if cross_check and str(rows[2][0]) == "0" and cross_title.upper() in str(rows[3][0] + " " + rows[4][0]).upper():
                            if wh_check and wh_title.upper() in str(rows[3][0]).upper():
                                datevalue = timevalue_convert(int(rows[0][0]))
                                db_data.append({"db_file":filename[:-5],"MODE":rows[2][0],"TITLE1":rows[3][0],"TITLE2":rows[4][0],"HEATS":rows[1][0], "DATE":datevalue})
                                if driver_rows:
                                    for b in driver_rows:
                                        driver_db_data.setdefault(filename[:-5], []).append({"CID": b[0], "FIRST_NAME": b[1], "LAST_NAME": b[2], "CLUB": b[3], "SNOWMOBILE": b[4]})
                                else:
                                    pass
                            elif wh_check == False:

                                datevalue = timevalue_convert(int(rows[0][0]))
                                db_data.append({"db_file":filename[:-5],"MODE":rows[2][0],"TITLE1":rows[3][0],"TITLE2":rows[4][0],"HEATS":rows[1][0], "DATE":datevalue})
                                if driver_rows:
                                    for b in driver_rows:
                                        driver_db_data.setdefault(filename[:-5], []).append({"CID": b[0], "FIRST_NAME": b[1], "LAST_NAME": b[2], "CLUB": b[3], "SNOWMOBILE": b[4]})
                                else:
                                    pass

                        elif wh_check == False and cross_check == False:
                            datevalue = timevalue_convert(int(rows[0][0]))
                            db_data.append({"db_file":filename[:-5],"MODE":rows[2][0],"TITLE1":rows[3][0],"TITLE2":rows[4][0],"HEATS":rows[1][0], "DATE":datevalue})
                            if driver_rows:
                                for b in driver_rows:
                                    driver_db_data.setdefault(filename[:-5], []).append({"CID": b[0], "FIRST_NAME": b[1], "LAST_NAME": b[2], "CLUB": b[3], "SNOWMOBILE": b[4]})
                            else:
                                pass

                        elif wh_title.upper() in str(rows[3][0]).upper() and cross_check == False:
                            datevalue = timevalue_convert(int(rows[0][0]))
                            db_data.append({"db_file":filename[:-5],"MODE":rows[2][0],"TITLE1":rows[3][0],"TITLE2":rows[4][0],"HEATS":rows[1][0], "DATE":datevalue})
                            if driver_rows and event_only == False:
                                for b in driver_rows:
                                    driver_db_data.setdefault(filename[:-5], []).append({"CID": b[0], "FIRST_NAME": b[1], "LAST_NAME": b[2], "CLUB": b[3], "SNOWMOBILE": b[4]})

    return db_data, driver_db_data

def init_database(event_files, driver_db_data, g_config, init_mode=True, exclude_lst=False):
    db_location = g_config["db_location"]
    for entry in event_files:
        with sqlite3.connect(db_location + "/" + entry["db_file"]+".sqlite") as conn:
            
            cursor = conn.cursor()

            if init_mode:
                #Create index table
                cursor.execute('''
                CREATE TABLE IF NOT EXISTS db_index (
                    MODE INTEGER,
                    RUNS INTEGER,
                    DB_FILE TEXT,
                    TITLE1 TEXT,
                    TITLE2 TEXT,
                    DATE
                )
                ''')

                cursor.execute('''
                CREATE TABLE IF NOT EXISTS drivers (
                    CID INTEGER PRIMARY KEY,
                    FIRST_NAME TEXT,
                    LAST_NAME TEXT,
                    CLUB TEXT,
                    SNOWMOBILE TEXT 
                )
                ''')

                #Replace or insert event
                cursor.execute('''
                REPLACE INTO db_index (MODE, RUNS, DB_FILE, TITLE1, TITLE2, DATE) VALUES (?, ?, ?, ?, ?, ?)
                ''', (entry["MODE"], entry["HEATS"], entry["db_file"], entry["TITLE1"], entry["TITLE2"], entry["DATE"]))

                print("Added:", entry["db_file"], entry["MODE"])

                driver_insert_data = []

                if len(driver_db_data) > 0: 
                    try:
                        for driver_data in driver_db_data[entry["db_file"]]:
                            cid = driver_data['CID']
                            first_name = driver_data['FIRST_NAME']
                            last_name = driver_data['LAST_NAME']
                            club = driver_data['CLUB']
                            snowmobile = driver_data['SNOWMOBILE']
                            
                            driver_data_tuple = (cid, first_name, last_name, club, snowmobile)
                            driver_insert_data.append(driver_data_tuple)
                    except:
                        pass

                #Turning driver data into tuple
                sql = "INSERT OR IGNORE INTO drivers (CID, FIRST_NAME, LAST_NAME, CLUB, SNOWMOBILE) VALUES (?, ?, ?, ?, ?);"
                cursor.executemany(sql, driver_insert_data)


                #Add all the heats
                for a in range(0, int(entry["HEATS"])):
                    heat = (a + 1)
                    cursor.execute('''
                    CREATE TABLE IF NOT EXISTS startlist_r{0} (
                        CID_ORDER INTEGER PRIMARY KEY AUTOINCREMENT,
                        CID INTEGER,
                        FOREIGN KEY(CID) REFERENCES drivers(CID)
                    )
                    '''.format(heat))

                    cursor.execute('''
                    CREATE TABLE IF NOT EXISTS driver_stats_r{0} (
                        CID INTEGER PRIMARY KEY,
                        INTER_1 INTEGER,
                        INTER_2 INTEGER,
                        INTER_3 INTEGER,
                        SPEED INTEGER,
                        REACTION INTEGER,
                        PENELTY INTEGER,
                        FINISHTIME INTEGER,
                        LOCKED INTEGER DEFAULT "0" NOT NULL,
                        STATE INTEGER DEFAULT "0",
                        FOREIGN KEY(CID) REFERENCES drivers(CID)
                    )
                    '''.format(heat))
                    conn.commit()

def calculate_kvali_nr(event_dict):
    from app.models import EventKvaliRate
    from app import db as my_db

    # Delete all existing records and commit immediately
    EventKvaliRate.query.delete()
    my_db.session.commit()

    count = 0
    for event, value in event_dict.items():
        count += 1
        kvalinr = 16 if value >= 16 else 8 if value >= 8 else 4 if value >= 4 else 2 if value >= 2 else 1 if value >= 1 else 0
        
        try:
            record = EventKvaliRate(id=count, event=event, kvalinr=kvalinr)
            my_db.session.add(record)
            my_db.session.commit()
        except Exception as e:
            my_db.session.rollback()
            print(f"Error inserting record for event '{event}': {str(e)}")
            raise

    print("All records inserted successfully")
        

def insert_driver_stats(db, g_config, exclude_lst=False, init_mode=True, sync=False):

    from app.models import ActiveEvents
    from app import db as my_db
    from app.models import Session_Race_Records, CrossConfig
    

    event_dict_kvali = {}

    event_dir = g_config["event_dir"]
    db_location = g_config["db_location"]
    
    current_title = None

    try:
        for a in db:
            if "SPESIFIC_HEAT" in a.keys():
                spesific_heat = a["SPESIFIC_HEAT"]
            else:
                spesific_heat = False

            if "MODE" not in a.keys():
                mode = str(my_db.session.query(ActiveEvents.mode).filter(ActiveEvents.event_file == a["db_file"]).first()[0])
                if spesific_heat == False:
                    heats = my_db.session.query(ActiveEvents).filter(ActiveEvents.event_file == a["db_file"]).count()
                else:
                    heats = 1
            else:
                mode=a["MODE"]
                heats=a["HEATS"]

            local_event_db = db_location+a["db_file"]+".sqlite"
            ext_event_db = event_dir+a["db_file"]+"Ex.scdb"


            event_db_path = ext_event_db
            main_db_path = local_event_db

            print("Inserting data for " + event_db_path)
            for b in range(0, int(heats)):
                if g_config["cross"]:
                    pass
                else:
                    start_time_query = None 

                if spesific_heat != False:
                    heat = spesific_heat
                else:
                    heat = (b + 1)

                if g_config["cross"] and mode == str(0):
                    start_time_query = f"SELECT C_NUM, C_HOUR2 FROM TTIMERECORDS_HEAT{heat}_START"
                    query = f"SELECT C_NUM, C_INTER1, C_INTER2, C_INTER3, C_SPEED1, C_STATUS, C_TIME FROM TTIMEINFOS_HEAT{heat}"


                elif mode == str(3):
                    heat_count = my_db.session.query(ActiveEvents).filter(ActiveEvents.event_file == a["db_file"]).count()
                    if spesific_heat == False:
                        heat_count = (heat_count - int(heat)) +1 
                    else:
                        heat_count = (heat_count - int(heat)) +1 

                    query = f"SELECT C_NUM, C_INTER1, C_INTER2, C_INTER3, C_SPEED1, C_STATUS, C_TIME, C_DATA2 FROM TTIMEINFOS_PARF_HEAT{heat_count}_RUN1"

                else:
                    query = f"SELECT C_NUM, C_INTER1, C_INTER2, C_INTER3, C_SPEED1, C_STATUS, C_TIME, C_DATA2 FROM TTIMEINFOS_HEAT{heat}"


                    
                try:
                    with sqlite3.connect(event_db_path) as conn:
                        cursor = conn.cursor()
                        cursor.execute(query)
                        time_data = cursor.fetchall()
                        time_data_lst = []

                        if g_config["cross"] and mode == str(0):
                            cursor.execute(start_time_query)
                            start_time_data = cursor.fetchall()
                            time_data_lst = [
                                {
                                    "CID": data[0], "INTER_1": data[1], "INTER_2": data[2], "INTER_3": data[3],
                                     "REACTION": data[7], "SPEED": data[4], "PENELTY": data[5], "FINISHTIME": data[6]
                                } 
                                for data in time_data
                            ]

                            start_time_lst = [
                                {
                                    "CID": data[0], "START": data[1]
                                } 
                                for data in start_time_data
                            ]

                        else:
                            if mode == str(2):
                                for data in time_data:
                                    if data[1] == 0 and data[6] == 0 and data[2] == 0 and data[5] == 0:
                                        inter_time = 1
                                    else:
                                        inter_time = 0

                                    time_data_lst.append({"CID": data[0], "INTER_1": inter_time, "INTER_2": data[2], "INTER_3": data[2],"SPEED": data[4], "REACTION": data[7], "PENELTY": data[5], "FINISHTIME": data[6]})
                            else:
                                for data in time_data:
                                    time_data_lst.append({"CID": data[0], "INTER_1": data[1], "INTER_2": data[2], "INTER_3": data[2],"SPEED": data[4], "REACTION": data[7], "PENELTY": data[5], "FINISHTIME": data[6]})


                except Exception as e:
                    print("No session data inserted for, " + event_db_path)
                    print(e)
                    continue

                with sqlite3.connect(main_db_path) as conn:
                    cursor = conn.cursor()
                    sql = "SELECT * FROM startlist_r{0};".format(heat)
                    startlist = cursor.execute(sql).fetchall()
                    startlist_lst = [g[1] for g in startlist]
                    tmp_driver = [l["CID"] for l in time_data_lst]

                    #Get the driver_list to updated the internal Flask DB
                    cursor.execute("SELECT * FROM drivers")
                    driver_list = cursor.fetchall()
                    cursor.execute("SELECT TITLE1, TITLE2 FROM db_index;")
                    event_name = cursor.fetchall()

                    if g_config["cross"] and mode == str(0):
                        
                        for v in startlist_lst:
                            inter_1 = None

                            for t in start_time_lst:

                                if t["CID"] == v:
                                    inter_1 = t["START"]


                            if inter_1 == None:
                                inter_1 = 0

                            if v not in tmp_driver:                                
                                time_data_lst.append({
                                    "CID": v, 
                                    "INTER_1": 0, 
                                    "INTER_2": 0, 
                                    "INTER_3": 0,
                                    "REACTION":0,
                                    "SPEED": 0, 
                                    "PENELTY": 0, 
                                    "FINISHTIME": 0
                                })

                        for t in time_data_lst:
                            for h in start_time_lst:
                                if t["CID"] == h["CID"]:
                                    t["INTER_1"] = h["START"]
                                
                    else:


                        for v in startlist_lst:
                            if v not in tmp_driver:
                                time_data_lst.append({
                                    "CID": v, 
                                    "INTER_1": 0, 
                                    "INTER_2": 0, 
                                    "INTER_3": 0,
                                    "REACTION":0,
                                    "SPEED": 0, 
                                    "PENELTY": 0, 
                                    "FINISHTIME": 0
                                })

                    session_data = {}

                    if init_mode:

                        timedata_tuples = [
                            (d["INTER_1"], d["INTER_2"], d["INTER_3"] ,d["SPEED"], d["PENELTY"], d["FINISHTIME"], d["CID"], d["REACTION"]) 
                            for d in time_data_lst
                        ]
                        
                        for x in time_data_lst:
                            for b in driver_list:
                                if int(x["CID"]) == int(b[0]):
                                    session_data[b[0]] = [b[1], b[2], event_name[0][0], event_name[0][1], heat, x["FINISHTIME"], b[4], x["PENELTY"], x["REACTION"]]
                        for key, value in session_data.items():
                            record = Session_Race_Records(first_name=value[0], last_name=value[1], title_1=value[2], title_2=value[3], heat=value[4], finishtime=value[5], snowmobile=value[6], penalty=int(value[7]), reaction=int(value[8]))
                            my_db.session.add(record)

                        my_db.session.commit()

                        #sql = f"""
                        #INSERT OR REPLACE INTO driver_stats_r{heat} 
                        #(INTER_1, INTER_2, INTER_3, SPEED, PENELTY, FINISHTIME, CID) 
                        #VALUES (?, ?, ?, ?, ?, ?, ?)
                        #"""
                        #cursor.executemany(sql, timedata_tuples)
                        
                    else:

                        if exclude_lst:
                            query = f"SELECT CID from driver_stats_r{str(heat)} WHERE LOCKED = 1"
                            cursor.execute(query)
                            locked_cids = [item[0] for item in cursor.fetchall()]
                            timedata_tuples = [
                                (d["INTER_1"], d["INTER_2"], d["INTER_3"], d["SPEED"], d["PENELTY"], d["FINISHTIME"], d["CID"], d["REACTION"]) 
                                for d in time_data_lst if d["CID"] not in locked_cids
                            ]

                            cursor.execute(f'DELETE FROM driver_stats_r{heat} WHERE LOCKED != 1;')
                            
                        else:
                            timedata_tuples = [
                                (d["INTER_1"], d["INTER_2"], d["INTER_3"], d["SPEED"], d["PENELTY"], d["FINISHTIME"], d["CID"], d["REACTION"]) 
                                for d in time_data_lst
                            ]
                            cursor.execute(f'DELETE FROM driver_stats_r{heat}')
                    


                    sql = f"""
                    INSERT OR REPLACE INTO driver_stats_r{heat} 
                    (INTER_1, INTER_2, INTER_3, SPEED, PENELTY, FINISHTIME, CID, REACTION) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """
                    if len(timedata_tuples) == 0:
                        continue
                    for x in timedata_tuples:
                        for b in driver_list:
                            if int(x[6]) == int(b[0]):
                                session_data[b[0]] = [b[1], b[2], event_name[0][0], event_name[0][1], heat, x[5], b[4], x[4], x[7]]

                    current_title = session_data[list(session_data.keys())[0]][2] + " " + session_data[list(session_data.keys())[0]][3]
                    

                    if mode == str(0) and g_config["cross"] and g_config["wl_cross_title"] in current_title:
                         cross_config = CrossConfig.query.first()
                         driver_scores = cross_config.driver_scores
                         dnf_score = cross_config.dnf_point
                         dns_score = cross_config.dns_point
                         dsq_score = cross_config.dsq_point
                         invert_score = cross_config.invert_score

                         sorted_drivers = sorted(session_data.items(), key=lambda x: x[1][5])
                         if not invert_score:
                            finished_drivers = 0
                            for index in sorted_drivers:
                                if index[1][5] != 0 and index[1][7] == 0:
                                    finished_drivers += 1

                         if len(cross_config.driver_scores) >= len(session_data):

                            penalty_points = {'3': dsq_score, '1': dns_score, '2': dnf_score}
                            for driver_id, driver_info in session_data.items():
                                penalty_code = driver_info[7]
                                if str(penalty_code) in str(penalty_points.keys()):
                                    driver_info.append(penalty_points[str(penalty_code)])

                                else:
                                    driver_info[7] = 0
                            
                            sorted_drivers = sorted(session_data.items(), key=lambda x: (x[1][-1] != 0, x[1][5]))

                            position = 1
                            first = True
                            for driver_id, driver_info in sorted_drivers:
                                if driver_info[7] == 0 and driver_info[5] != 0:
                                    position_str = str(position)

                                    if position_str in driver_scores:
                                        if not invert_score:
                                            driver_info.append(driver_scores[str(len(driver_scores) - int(finished_drivers))])
                                            if first:
                                                finished_drivers -= 2
                                                first = False
                                            else:
                                                finished_drivers -= 1

                                        else:
                                            driver_info.append(driver_scores[position_str])
                                    else:
                                        driver_info.append(0)
                                    position += 1 
                                elif driver_info[5] == 0 and driver_info[7] == 0:
                                    driver_info.append(0)

                                session_data[driver_id] = driver_info

                    for value in session_data:
                        if len(session_data[value]) == 9:
                            session_data[value].append("0")

                        my_db.session.query(Session_Race_Records)\
                            .filter(Session_Race_Records.first_name == session_data[value][0])\
                            .filter(Session_Race_Records.last_name == session_data[value][1])\
                            .filter(Session_Race_Records.title_1 == session_data[value][2])\
                            .filter(Session_Race_Records.title_2 == session_data[value][3])\
                            .filter(Session_Race_Records.heat == session_data[value][4])\
                            .delete()

                        my_db.session.commit()
                        
                        if "Kvalifisering" in session_data[value][3]:
                            if session_data[value][3] not in event_dict_kvali.keys():
                                event_dict_kvali[session_data[value][3]] = len(session_data)
                            session_data[value][8] = 0

                        record = Session_Race_Records(cid=value, first_name=session_data[value][0], last_name=session_data[value][1], title_1=session_data[value][2], title_2=session_data[value][3], heat=session_data[value][4], finishtime=session_data[value][5], snowmobile=session_data[value][6], penalty=int(session_data[value][7]), points=int(session_data[value][9]), reaction=session_data[value][8])
                        my_db.session.add(record)

                    my_db.session.commit()
                    cursor.executemany(sql, timedata_tuples)
                    
        if init_mode:
            if bool(g_config["keep_qualification"]) == False:
                calculate_kvali_nr(event_dict_kvali)

    except Exception as e:
        print("An exception occurred:", str(e))
        traceback.print_exc()

                        
def insert_start_list(db, g_config, init_mode=True, set_active_driver=False):
    from app.models import ActiveEvents
    from app import db as my_db
    from app.lib.utils import Set_active_driver
    event_dir = g_config["event_dir"]
    db_location = g_config["db_location"]
    if set_active_driver == True:
        SPESIFIC_HEAT = db[0]["SPESIFIC_HEAT"]

    for a in db:
        if "MODE" not in a.keys():
            mode = my_db.session.query(ActiveEvents.mode).filter(ActiveEvents.event_file == a["db_file"]).first()[0]
            heats = my_db.session.query(ActiveEvents).filter(ActiveEvents.event_file == a["db_file"]).count()
        else:
            mode=a["MODE"]
            heats=a["HEATS"]

        if "SPESIFIC_HEAT" in a.keys():
            spesific_heat = a["SPESIFIC_HEAT"]
        else:
            spesific_heat = False

        local_event_db = db_location+a["db_file"]+".sqlite"
        ext_event_db = event_dir+a["db_file"]+"Ex.scdb"

        for b in range(0, int(heats)):
            startlist_data = ""
            heat = (b + 1)

            with sqlite3.connect(ext_event_db) as conn:
                
                cursor = conn.cursor()
                try:
                    if str(mode) == "0":
                        cursor.execute("SELECT C_NUM FROM TSTARTLIST_HEAT{0};".format(heat))

                    elif str(mode) == "2":

                        cursor.execute("SELECT C_NUM FROM TSTARTLIST_PARQ2_HEAT{0};".format(heat))

                    elif str(mode) == "3":   
                        
                        if spesific_heat != False:
                            heat_inverted = (int(heats) - int(heat)) +1
                            
                        else:
                            heat_inverted = (int(heats) - int(heat)) +1

                        cursor.execute("SELECT C_NUM FROM TSTARTLIST_PARF_HEAT{0};".format(heat_inverted)) 
                    else:
                        return False
                
                except Error as e:
                    print(e)
                startlist_data = cursor.fetchall()
                if len(startlist_data) == 0:
                    print("No drivers")
                    continue
                
                if set_active_driver and int(SPESIFIC_HEAT) == int(heat):
                    Set_active_driver(startlist_data[0][0])

            with sqlite3.connect(local_event_db) as conn_new_db:
                cursor_new = conn_new_db.cursor()
                if init_mode == False:
                    #NO IDEA WHY I ADDED THIS, WILL PROBABLY FIND OUT IN THE FUTURE
                    #cursor_new.execute(f'DELETE FROM driver_stats_r{heat}')
                    cursor_new.execute(f'DELETE FROM startlist_r{heat}')
                    
                try:
                    sql = "INSERT INTO startlist_r{0} (CID) VALUES (?)".format(heat)
                    cursor_new.executemany(sql, startlist_data)

                except Error as e:
                    print(e)

                conn_new_db.commit()   
