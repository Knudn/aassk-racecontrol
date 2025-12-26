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
    from app import db
    from sqlalchemy import func


    g_config = GetEnv()

    delete_events(g_config["db_location"], event=Event)
    
    print(g_config) 
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

    g_config = GetEnv()

    update_active_event(g_config)
    active_event = get_active_event()

    change_active_driver = False


    if current_app.config['current_event'] != active_event:
        current_app.config['current_event'] = active_event
        change_active_driver = True
    
    #print(event, heat)
    #db_data, driver_db_data = map_database_files(g_config, "Event008")
    #print(db_data, driver_db_data)
    try:

        insert_start_list(active_event, g_config, init_mode=False, set_active_driver=change_active_driver)
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
    data = json.dumps(format_startlist(event))

    return data


def get_active_startlist_w_timedate(upcoming=False, event_wl=None, event_comb=None):
    from app.models import ActiveEvents

    g_config = GetEnv()

    if event_comb != None:
        combined_data = []
        event_comb_old = event_comb
        for k, b in enumerate(event_comb_old):
            event_db_file = (g_config["db_location"]+b[0]["db_file"]+".sqlite")
            
            event_comb[k][0]["db_file"] = event_db_file
            data = format_startlist([event_comb[k][0]], include_timedata=True)
            combined_data.append(data)

        return combined_data


    if event_wl != None:
        event_db_file = (g_config["db_location"]+event_wl[0]["db_file"]+".sqlite")
        event_wl[0]["db_file"] = event_db_file
        data = format_startlist(event_wl, include_timedata=True)
        return data

    event = get_active_event()
    
    current_db_file = event[0]["db_file"]
    current_heat = event[0]["SPESIFIC_HEAT"]

    if upcoming == True:

        current_entry = ActiveEvents.query.filter_by(event_file=current_db_file, run=current_heat).first()

        upcoming_entry = (ActiveEvents.query
                        .filter(ActiveEvents.sort_order > current_entry.sort_order,
                                ActiveEvents.enabled == 1
                                )
                        .order_by(ActiveEvents.sort_order.asc())
                        .first())
        
        
        event_file = upcoming_entry.event_file
        event_heat = upcoming_entry.run
        
        event_db_file = (g_config["db_location"]+event_file+".sqlite")
        event[0]["SPESIFIC_HEAT"] = event_heat

        event[0]["db_file"] = event_db_file


    else:
        
        
        event_db_file = (g_config["db_location"]+event[0]["db_file"]+".sqlite")

        event[0]["db_file"] = event_db_file

    data = format_startlist(event, include_timedata=True)
    #data = json.dumps(format_startlist(event, include_timedata=True))

    return data

def get_specific_event_data(event_filter=None):

    g_config = GetEnv()
    if event_filter != None:
        event = event_filter
    else:
        event = get_active_event()
    
    event_db_file = (g_config["db_location"]+event[0]["db_file"]+".sqlite")
    event[0]["db_file"] = event_db_file
    data = get_event_data_all(event)
    print(data)
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

    return [{"db_file": "Event"+str(event), "SPESIFIC_HEAT": str(data.Heat)}]
    
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

