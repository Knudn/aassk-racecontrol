import os
import time
import shutil
import sqlite3
import requests
import xml.etree.ElementTree as ET
import traceback
from typing import Dict, Set
import time
import json

# Configuration
FIFO_PATH = '/tmp/file_monitor_fifo'
ACTIVE_EVENT_QUERY = "SELECT C_VALUE FROM TPARAMETERS WHERE C_PARAM = 'HEAT' OR C_PARAM = 'EVENT';"
MODE_QUERY = "SELECT C_VALUE FROM TPARAMETERS WHERE C_PARAM='MODULE';"

DB_PATH = "site.db"

with sqlite3.connect(DB_PATH) as con:
    cur = con.cursor()
    g_config = cur.execute("SELECT wl_cross_title, wl_bool, wl_title from global_config;").fetchone()

wl_bool = g_config[1]

if bool(wl_bool) == True:
    wl_title = g_config[2]
    wl_cross_title = g_config[0]

main_dict = {} 
active_event = []

event_name = ""

def xml_to_dict(file):
    if type(file) == str:

        with open(file, "r") as f:
            file_read = f.read()

        element = ET.fromstring(file_read)
    else:
        element = file 
    result = dict(element.attrib)
    
    if element.text and element.text.strip():
        result['_text'] = element.text.strip()
    
    for child in element:
        if len(child.items()) == 1:
            if child.items()[0][1] == "timeofday":
                child.text = ""
            
            if child.items()[0][1] == "racetime":
                child.text = ""

        child_data = xml_to_dict(child)
        if child.tag in result:
            if not isinstance(result[child.tag], list):
                result[child.tag] = [result[child.tag]]
            result[child.tag].append(child_data)
        else:
            result[child.tag] = child_data
    
    return result

def index_current():
    global main_dict
    current_files = [a.path for a in os.scandir("/mnt/intermediate/") if "scdb" in a.path and not "Ex" in a.path and not "Online" in a.path]
    
    tmp_index = []
    tmp_driver_lst = []
    for a in current_files: 
        with sqlite3.connect(a) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT C_VALUE FROM TPARAMETERS WHERE C_PARAM='TITLE1' OR C_PARAM='TITLE2' or C_PARAM='HEAT_NUMBER';")
            event_content = cursor.fetchall()
            
            if str(event_content) == "[]":
                continue
            
            
            df = [item[0] for item in event_content]
            if wl_bool:
                if not wl_title in (df[1] + df[2]):
                    continue
            
            cursor.execute("SELECT C_NUM, C_FIRST_NAME, C_LAST_NAME, C_CLUB, C_TEAM FROM TCOMPETITORS;")
            drivers = [driv for driv in cursor.fetchall()]
            file = os.path.split(a)[-1]
            main_dict[df[2]] = {"event_file":file, "event_name":df[1], "heats":df[0]}
            
            #main_dict[file] 
            #itmp_index.append([file,df[0], df[1]])
                        
        ex_file = a.replace(".scdb", "Ex.scdb")
        
        with sqlite3.connect(ex_file) as conn:
            cursor_new = conn.cursor()
            heat_index = []
            main_dict[df[2]]["heat_ent"] = {} 
            for heat in range(0,int(df[0])):
                try:
                    heat = heat + 1
                    q = f"select C_NUM from TSTARTLIST_HEAT{heat};"
                    cursor_new.execute(q)
                    cids = [c[0] for c in cursor_new.fetchall()]
                    main_dict[df[2]]["heat_ent"][str(heat)] = {"time":"", "laps":0}
                    main_dict[df[2]]["heat_ent"][str(heat)]["drivers"] = []
                    for driv in drivers:
                        if driv[0] in cids:
                            dv_dict = {
                                "cid": driv[0],
                                "first_name": driv[1],
                                "last_name": driv[2],
                                "club": driv[3],
                                "snowmobile": driv[4],
                                "totale_time": 0,
                                "laps":0,
                                "best_time":0,
                                "finish_laps":0
                            }
                            main_dict[df[2]]["heat_ent"][str(heat)]["drivers"].append(dv_dict)
                
                except Exception as err:
                    print(err)
                    print("Error adding drivers in main dict during init")
                    main_dict[df[2]]["heat_ent"][str(heat)] = {"time":""}
                    main_dict[df[2]]["heat_ent"][str(heat)]["drivers"] = []


    return main_dict

def get_new_db_file():

    db_file = ""
    
    existing_files = os.listdir("/mnt/intermediate/")

    for num in range(33,999):
        db_file = f"Event{str(num).zfill(3)}.scdb"
        if db_file not in existing_files:
            break
    return db_file

def set_active_event(heat, run_name):
    global event_name

    json_data = {
        'driver_one': 0,
        'driver_two': 0,
        'event': f'{event_name} {run_name}',
        'event_heat': f'{heat}',
    }

    requests.post(
        'http://192.168.1.50:7777/api/set_active_state',
        json=json_data,
        verify=False,
    )    


def extract_driver_data(data, finish_on_lap):
    tmp_driver_data_lst = []

    if isinstance(data, dict):
        data = [data]
    for a in data:
        first_name = a["firstname"]
        last_name = a["lastname"]
        laps = a["laps"] if a["laps"] != '' else 0  
        pen = a["position"]
        cid = a["no"]
        club = a["additional5"]
        snowmobile = a["additional1"]
        best_time = a["besttime"]
        if int(laps) >= int(finish_on_lap):
            totale_time = a["totaltime"]
        else:
            totale_time = 0
        tmp_driver_data = {
            "cid": cid,
            "first_name": first_name,
            "last_name": last_name,
            "club": club,
            "snowmobile": snowmobile,
            "totaltime": totale_time,
            "laps": laps,
            "pen": pen,
            "best_time": best_time
        }
        tmp_driver_data_lst.append(tmp_driver_data)
    
    return tmp_driver_data_lst


def proc_current(current_dict):
    global main_dict
    heat_has_timentries = False
    current_flag = None
    laps_to_go = None

    for a in current_dict["label"]:
        if a["type"] == "runname":
            run_name = a["_text"]
        
        elif a["type"] == "groupname":
            group_name = a["_text"]
        elif a["type"] == "runtype":
            type_name = a["_text"]
            if type_name == "Q":
                type_name = "Qualifying"
            elif type_name == "R":
                type_name = "Race"
            elif type_name == "P":
                type_name = "Practice"

        elif a["type"] == "leadermargin" and "_text" in a:
            heat_has_timentries = True
        
        elif a["type"] == "flag":
            current_flag = a["_text"]
        elif a["type"] == "lapstogo" and "_text" in a:
            laps_to_go = a["_text"]

    heat, run_name, heats = normalize_run_name(group_name, run_name, type_name)
    
    if not heat_has_timentries and (current_flag == 'none' or current_flag == 'warmup') and laps_to_go != None:
        main_dict[run_name]["heat_ent"][heat]["laps"] = laps_to_go

    main_dict[run_name]["heat_ent"][heat]["drivers"] = []
    
    finish_on_lap = main_dict[run_name]["heat_ent"][heat]["laps"]

    if "result" in current_dict["results"]:
        driver_data = extract_driver_data(current_dict["results"]["result"], finish_on_lap)
        main_dict[run_name]["heat_ent"][heat]["drivers"].append(driver_data)
    
    




def create_scdb(filename):
    print("Created", filename)
    query = "CREATE TABLE IF NOT EXISTS 'TPARAMETERS' ('C_PARAM' CHAR(32) NOT NULL, 'C_VALUE'	VARCHAR(510), PRIMARY KEY('C_PARAM'));"
    query_2 = "CREATE TABLE IF NOT EXISTS 'TCOMPETITORS' ('C_NUM' INTEGER, 'C_LAST_NAME' VARCHAR(60), 'C_FIRST_NAME'	VARCHAR(60), 'C_CLUB' VARCHAR(60), 'C_TEAM' VARCHAR(60), PRIMARY KEY('C_NUM'));"
    with sqlite3.connect("/mnt/intermediate/"+filename) as conn:
        cursor = conn.cursor()
        cursor.execute(query)
        cursor.execute(query_2)

def update_scdb(event_data, run_name):
    global event_name

    event_file = event_data["event_file"]
    driver_lst_cid = []
    driver_lst = []
    heats = event_data["heats"]

    
    for a in event_data["heat_ent"]:
        if len(event_data["heat_ent"][a]["drivers"]) > 0:
            for b in event_data["heat_ent"][a]["drivers"][0]:
                if isinstance(b, dict):
                    if b["cid"] not in driver_lst_cid:
                        driver_data_tuple = (b["cid"], b["first_name"], b["last_name"], b["club"], b["snowmobile"])
                        driver_lst.append(driver_data_tuple)
                        driver_lst_cid.append(b["cid"])
    
    with sqlite3.connect("/mnt/intermediate/"+event_file) as conn:

        cursor = conn.cursor()
        q_clear_tp = "DELETE FROM TPARAMETERS;"
        q_clear_tc = "DELETE FROM TCOMPETITORS"
        cursor.execute(q_clear_tp)
        cursor.execute(q_clear_tc)
        

        cursor.execute("INSERT OR REPLACE INTO TPARAMETERS (C_PARAM, C_VALUE) VALUES ('TITLE1', ?);", (event_name,))
        cursor.execute("INSERT OR REPLACE INTO TPARAMETERS (C_PARAM, C_VALUE) VALUES ('TITLE2', ?);", (run_name,))
        cursor.execute("INSERT OR REPLACE INTO TPARAMETERS (C_PARAM, C_VALUE) VALUES ('MODULE', '0');")
        cursor.execute("INSERT OR REPLACE INTO TPARAMETERS (C_PARAM, C_VALUE) VALUES ('DATE', ?);", (str(int(time.time())),))
        cursor.execute("INSERT OR REPLACE INTO TPARAMETERS (C_PARAM, C_VALUE) VALUES ('HEAT_NUMBER', ?);", (str(heats),))

        
        q_add_entries_drivers = "INSERT INTO TCOMPETITORS (C_NUM, C_FIRST_NAME, C_LAST_NAME, C_CLUB, C_TEAM) VALUES (?, ?, ?, ?, ?);"
        cursor.executemany(q_add_entries_drivers, driver_lst)
    
def update_scdb_ex(event_data, run_name, heat):

    filename = event_data["event_file"].replace(".scdb","Ex.scdb")
    start_list_cid = []
    driver_times = []
    if len(event_data["heat_ent"][heat]["drivers"]) == 0:

        with sqlite3.connect("/mnt/intermediate/"+filename) as conn:
            cursor = conn.cursor()
            cursor.execute(f"DELETE FROM TSTARTLIST_HEAT{heat};")
            cursor.execute(f"DELETE FROM TTIMEINFOS_HEAT{heat};")
        
        print("No drivers in:", run_name + ":" + heat )
        return 
    
    for k, a in enumerate(event_data["heat_ent"][heat]["drivers"][0]):
        entry = (k+1,a["cid"], "0")

        if a["pen"] == "DNF":
            pen_code = 2
        elif a["pen"] == "DQ":
            pen_code = 3
        elif a["pen"] == "DNS":
            pen_code = 1
        else:
            pen_code = 0
        if a["totaltime"] == '':
            totaltime = 0
        else:
            totaltime = a["totaltime"]
        best_time = a["best_time"]
        driver_times_tmp = (a["cid"],totaltime,a["laps"],"0","0","0",best_time, pen_code)
        driver_times.append(driver_times_tmp)
        start_list_cid.append(entry)

    insert_startlist_q = f"INSERT INTO TSTARTLIST_HEAT{heat} (C_LINE, C_NUM, C_START) VALUES (?,?,?)"
    insert_times_q = f"INSERT INTO TTIMEINFOS_HEAT{heat} (C_NUM, C_TIME, C_INTER1, C_INTER2, C_INTER3, C_SPEED1, C_DATA2, C_STATUS) VALUES (?,?,?,?,?,?,?,?)"
    


    with sqlite3.connect("/mnt/intermediate/"+filename) as conn:
        cursor = conn.cursor()
        cursor.execute(f"DELETE FROM TSTARTLIST_HEAT{heat};")
        cursor.execute(f"DELETE FROM TTIMEINFOS_HEAT{heat};")
        cursor.executemany(insert_startlist_q, start_list_cid)
        cursor.executemany(insert_times_q, driver_times)


def create_scdb_ex(filename, heat=None, heats=None):
    filename = filename.replace(".scdb","Ex.scdb")

    if heats != None:
        for heat in range(0,heats):
            heat += 1 

            query = f"CREATE TABLE IF NOT EXISTS 'TTIMEINFOS_HEAT{heat}' ('C_NUM' INTEGER NOT NULL, 'C_STATUS' INTEGER, 'C_TIME' INTEGER, 'C_INTER1' INTEGER, 'C_INTER2' INTEGER, 'C_INTER3' INTEGER, 'C_SPEED1' INTEGER, 'C_DATA2' INTEGER, PRIMARY KEY('C_NUM'));"
            query_startlist = f"CREATE TABLE IF NOT EXISTS 'TSTARTLIST_HEAT{heat}'('C_LINE' INTEGER NOT NULL, 'C_NUM' INTEGER, 'C_START' INTEGER, PRIMARY KEY('C_LINE'));"
            
            with sqlite3.connect("/mnt/intermediate/"+filename) as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                cursor.execute(query_startlist)
    else:
        
        query = f"CREATE TABLE IF NOT EXISTS 'TTIMEINFOS_HEAT{heat}' ('C_NUM' INTEGER NOT NULL, 'C_STATUS' INTEGER, 'C_TIME' INTEGER, 'C_INTER1' INTEGER, 'C_INTER2' INTEGER, 'C_INTER3' INTEGER, 'C_SPEED1' INTEGER, 'C_DATA2' INTEGER, PRIMARY KEY('C_NUM'));"
        
        query_startlist = f"CREATE TABLE IF NOT EXISTS 'TSTARTLIST_HEAT{heat}'('C_LINE' INTEGER NOT NULL, 'C_NUM' INTEGER, 'C_START' INTEGER, PRIMARY KEY('C_LINE'));"
        
        with sqlite3.connect("/mnt/intermediate/"+filename) as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            cursor.execute(query_startlist)

def get_event_name():
    file_dict_event_name = xml_to_dict("/mnt/test/current.xml")
    event_name = ""
    for b in file_dict_event_name["label"]:
        if b["type"] == "eventname":
            event_name = b["_text"]
    return event_name

def remove_event_files(event):
    event_file = "/mnt/intermediate/"+event    
    event_file_ex = "/mnt/intermediate/"+event.replace(".scdb", "Ex.scdb")    
    print("Removing:",event_file)
    print("Removing:",event_file_ex)
    os.remove(event_file)
    os.remove(event_file_ex)

def build_schedule(sc_data):
    data = {"table_data":json.dumps(sc_data), "src":"orbits"}
    response = requests.post('http://192.168.1.50:7777/admin/active_events', data=data, verify=False)

def update_schedule(entry):
    global main_dict
    global event_name
    
    update_lst = []

    if event_name == "":
        event_name = get_event_name()

    check_dict = {}
    schedule_lst = []
    for k, results in enumerate(entry["results"]["result"]):
        k += 1

        heat, norm_group_name, heats = normalize_run_name(results["groupname"], results["runname"], results["runtype"])
        schedule_lst.append({"name":norm_group_name, "run":heat, "sort_order":k})

        if norm_group_name not in check_dict:
            check_dict[norm_group_name] = []
        
        check_dict[norm_group_name].append(heat)

        add_event = True
        if norm_group_name in main_dict:
            add_event = False
        
        if add_event:
            event_file = get_new_db_file()
            print("Added", norm_group_name)
            create_scdb(event_file)
            main_dict[norm_group_name] = {"event_file":event_file, "event_name":event_name, "heats":heats, "heat_ent":{}}
            update_lst.append(norm_group_name)
        else:
            print("Found:", norm_group_name)
        
        if str(heat) not in main_dict[norm_group_name]["heat_ent"]:
            main_dict[norm_group_name]["heat_ent"][str(heat)] = {"laps":0, "time":results["datetime"], "drivers":[]}
        
        if add_event:
            create_scdb_ex(event_file, heats=int(8))

        update_scdb(main_dict[norm_group_name], norm_group_name)
       # insert_scdb_ex(main_dict[norm_group_name], norm_group_name, heat)
    rm_list = []
    build_schedule(schedule_lst)
    for a in main_dict:
        for b in main_dict[a]["heat_ent"]:
            if a not in check_dict:
                rm_list.append([a,0])
                break
            if b not in check_dict[a]:
                rm_list.append([a,b])
        main_dict[a]["heats"] = len(main_dict[a]["heat_ent"])

    for a in rm_list:
        if a[1] == 0 and a[0]:
            remove_event_files(main_dict[a[0]]["event_file"])
            del main_dict[a[0]]

        else:
            main_dict[a[0]]["heats"] -= 1
            del main_dict[a[0]]["heat_ent"][a[1]]
     



def normalize_run_name(groupname, runname, runtype):
    if runtype == "Qualifying":
        try:
            heat = runname[-1]          
            norm_grup_name = groupname + " - Kvalifisering"
            heats = 0 
        except Exception as err:
            heats = 1
            norm_grup_name = runname
            heat = 1

    elif runtype == "Race":
        if "Kvali" in runname:

            heats = runname[-1]
            heat = runname[-1]          
            norm_grup_name = groupname + " - Kvalifisering"
        
        elif "C" in runname:
            heats = runname[-1]
            norm_grup_name = groupname + " - C Finale"
            heat = runname[-1]          
        
        elif "B" in runname:
            norm_grup_name = groupname + " - B Finale"
            heats = runname[-1]
            heat = runname[-1]
        else:
            heats = 1
            heat = 1
            norm_grup_name = groupname + " - " + runname
    else:
        heats = 1
        heat = 1
        norm_grup_name = groupname + " - " + runname

    return heat, norm_grup_name, heats


def file_monitor():
    tracking_dict = {}
    global main_dict
    global active_event
    main_dict = index_current()
    sc_proc = False
    old_entry = {}
    last_sc = ""
    force_update_no_drivers = False
    sleep_time = 0.1
    while True:
        dir_files = os.scandir("/mnt/test/")
        for file in dir_files:
            if "current.xml" in file.path or "schedule.xml" in file.path:
                if file.path not in tracking_dict:
                    tracking_dict[file.path] = 0
                
                if tracking_dict[file.path] < os.path.getmtime(file.path):
                    tracking_dict[file.path] = os.path.getmtime(file.path)
                    if "current.xml" in file.path and sc_proc:
                        old_main_dict = main_dict
                        file_dict = xml_to_dict(file.path)

                        if "result" not in file_dict["results"]:
                            no_drivers = True

                        if file_dict != old_entry:
                            print("Updated current!")
                            
                            for a in file_dict["label"]:
                                if a["type"] == "runname":
                                    runname = a["_text"]
                                
                                if a["type"] == "groupname":
                                    groupname = a["_text"]
                                
                                if a["type"] == "runtype":
                                    type_name = a["_text"]
                                    if type_name == "Q":
                                        type_name = "Qualifying"
                                    elif type_name == "R":
                                        type_name = "Race"
                                    elif type_name == "P":
                                        type_name = "Practice"

                            heat, run_name, heats = normalize_run_name(groupname, runname, type_name)
                            if active_event != [heat, run_name]:

                                set_active_event(heat, run_name)
                                active_event = [heat, run_name]
                                sleep_time = 1
                            else:
                                sleep_time = 0.1
                                
                            proc_current(file_dict)
                            update_scdb(main_dict[run_name], run_name)
                            update_scdb_ex(main_dict[run_name], run_name, heat)
                            
                            old_entry = file_dict

                            print("UPDATE!") 
                            requests.get("http://192.168.1.50:7777/api/active_event_update")

                    elif "schedule.xml" in file.path:
                        file_dict = xml_to_dict(file.path)
                        if last_sc != file_dict:
                            print("Updated schedule")
                            update_schedule(file_dict)

                        sc_proc = True

                        last_sc = file_dict
                    


        time.sleep(sleep_time)


file_monitor()

