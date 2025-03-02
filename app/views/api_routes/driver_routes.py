# app/api/driver_routes.py
from flask import request, current_app
import sqlite3
from app.lib.db_operation import get_active_event, get_active_startlist
from app.lib.utils import Set_active_driver, GetEnv, get_active_driver_name
from app.models import (
    ActiveDrivers,
    ActiveEvents,
    RetryEntries,
    Session_Race_Records
)
from app import db, socketio
from sqlalchemy import func
import json
import requests
from app.config.websocket_config import emit_to_room, SOCKET_ROOMS

def register_driver_routes(api_bp):
    """Register all driver-related routes with the API blueprint"""
    
    @api_bp.route('/api/update_active_drivers', methods=['GET', 'POST'])
    def update_active_drivers():
        if request.method == 'POST':
            # Process POST data to update active drivers
            return request.json
        else:
            return {"error": "Method not allowed"}, 405
    
    @api_bp.route('/api/start_status', methods=['GET', 'POST'])
    def start_status():
        if request.method == "POST":
            data = request.get_json()
            current_app.config['start_list_state'] = data
            return {"status": "Updated"}
        else:
            try:
                with sqlite3.connect("site.db") as con:
                    query = "SELECT D1, D2 FROM active_drivers;"
                    cur = con.cursor()
                    active_driver = cur.execute(query).fetchall()
                    D1 = active_driver[0][0]
                    D2 = active_driver[0][1]

                    for a in current_app.config['start_list_state']:
                        if int(D1) == int(a["CID"]) and a["STATUS"] == "STARTED":
                            return "STARTED"
                        elif int(D2) == int(a["CID"]) and a["STATUS"] == "STARTED":
                            return "STARTED"

                    return "FINISHED"
            except Exception as e:
                current_app.logger.error(f"Error in start_status: {str(e)}")
                return []
    
    @api_bp.route('/api/set_active_state', methods=['POST'])
    def set_active_state():
        data = request.json
        driver_one = data.get("driver_one")
        driver_two = data.get("driver_two")
        event = data.get("event")
        heat = data.get("event_heat")
        
        event_file = ActiveEvents.query.filter(
            ActiveEvents.event_name == data.get("event")).first()

        event_file_id = event_file.event_file[-3:]

        if int(event_file_id[0]) == 0 and int(event_file_id[1]) == 0:
            event_file_id = event_file_id[-1:]
        elif int(event_file_id[0]) == 0:
            event_file_id = event_file_id[-2:]

        current_active_state = ActiveDrivers.query.first()

        current_active_state.Event = event_file_id
        current_active_state.Heat = heat
        current_active_state.D1 = driver_one
        current_active_state.D2 = driver_two
        db.session.commit()
        
        # Import the send_data_to_room function
        from app.views.api_view import send_data_to_room
        send_data_to_room(get_active_startlist())
        
        return {"status": "success", "message": "Active state updated"}
    
    @api_bp.route('/api/ready_state', methods=['GET', 'POST'])
    def ready_state():
        g_config = GetEnv()

        DB_PATH = "site.db"
        query = "SELECT * FROM ACTIVE_DRIVERS;"
        with sqlite3.connect(DB_PATH) as con:
            cur = con.cursor()
            active_data = cur.execute(query).fetchall()

        D1 = active_data[0][3]
        event = active_data[0][1]
        heat = active_data[0][2]

        db_location = g_config["db_location"]
        current_event_file = db_location + "Event" + event.zfill(3) + ".sqlite"

        query = "SELECT startlist_r{0}.CID, driver_stats_r{0}.INTER_1, driver_stats_r{0}.FINISHTIME \
                FROM startlist_r{0} JOIN driver_stats_r{0} ON startlist_r{0}.CID = driver_stats_r{0}.CID;".format(heat)

        with sqlite3.connect(current_event_file) as con:
            cur = con.cursor()
            driver_data = cur.execute(query).fetchall()

        push = False

        if request.method == "POST":
            for a in driver_data:
                if push == True:
                    Set_active_driver(cid_1=a[0])
                    return "4"
                if int(a[0]) == int(D1):
                    if str(a[1]) != str(0):
                        push = True

            return "1"
        else:
            for a in driver_data:
                if int(a[0]) == int(D1):
                    if a[1] != 0:
                        return "1"
                    else:
                        return "4"
            return "4"
    
    @api_bp.route('/api/get_start_position_cross', methods=['POST'])
    def get_start_position_cross():
        data = request.json
        driver_names = data.get('driverIds', [])
        event = data.get('event')
        event_filter = event.split("-")[0] + "- Kvalifisering"

        # Prepare a query to get the records
        drivers_points = []
        for name in driver_names:
            first_name, last_name = name.split('+')
            driver_record = Session_Race_Records.query.filter(
                Session_Race_Records.first_name == first_name,
                Session_Race_Records.last_name == last_name,
                Session_Race_Records.title_2.ilike(f"%{event_filter}%")
            ).order_by(Session_Race_Records.points).all()
            
            points = 0
            for a in driver_record:
                points += int(a.points)

            if driver_record:
                drivers_points.append([first_name + "+" + last_name, points])
            
        sorted_drivers = sorted(drivers_points, key=lambda x: x[1], reverse=True)
        
        # Step 1: Find duplicates based on scores
        scores = [score for name, score in sorted_drivers]
        duplicates = {score for score in scores if scores.count(score) > 1}

        # Step 2: Remove duplicates from the original list and keep a separate list of duplicates
        duplicates_list = []
        new_drivers_list = []

        for driver in sorted_drivers:
            if driver[1] in duplicates:
                duplicates_list.append(driver)
            else:
                new_drivers_list.append(driver)

        dub_dckt = {}
        for a in duplicates_list:
            if a[1] not in dub_dckt:
                dub_dckt[a[1]] = [a[0]]
            else:
                dub_dckt[a[1]].append(a[0])
        
        # Process duplicate scores
        new_order_dups_with_points = {}  # Temporary dictionary to hold names with points

        for h in dub_dckt:
            for g in dub_dckt[h]:
                first_name, last_name = g.split('+')
                driver_record = (Session_Race_Records.query
                                .filter(Session_Race_Records.first_name == first_name,
                                        Session_Race_Records.last_name == last_name,
                                        Session_Race_Records.points != 0,
                                        Session_Race_Records.title_2.ilike("%Kvalifisering%"))
                                .order_by(Session_Race_Records.heat.desc())
                                .first())
                if driver_record:
                    entry = (driver_record.first_name + "+" + driver_record.last_name, driver_record.points)
                    if h not in new_order_dups_with_points:
                        new_order_dups_with_points[h] = [entry]
                    else:
                        new_order_dups_with_points[h].append(entry)

        new_order_dups = {}
        for h, drivers_with_points in new_order_dups_with_points.items():
            sorted_drivers = sorted(drivers_with_points, key=lambda x: x[1], reverse=True)
            new_order_dups[h] = [name for name, points in sorted_drivers]

        corrected_list = []

        for points, names in new_order_dups.items():
            for name in names:
                for entry in duplicates_list:
                    if entry[0] == name:
                        corrected_list.append(entry)
                        break

        combined_list = new_drivers_list + corrected_list
        combined_list.sort(key=lambda x: x[1], reverse=True)

        return combined_list
    
    @api_bp.route('/api/retry_entries', methods=['POST', 'GET'])
    def retry_entries():
        from app.lib.db_operation import get_active_event
        
        active_event_file = get_active_event()
        active_entry = db.session.query(ActiveEvents.event_name, ActiveEvents.run, ActiveEvents.mode).filter(
            ActiveEvents.event_file == active_event_file[0]["db_file"]
        ).first()

        active_title_heat = active_entry[0] + str(active_entry[1])

        if request.method == 'POST':
            if request.json["method"] == "remove":
                cid = request.json["cid"]
                db.session.query(RetryEntries).filter(RetryEntries.cid == cid).delete()
                db.session.commit()
            else:
                cid = request.json["cid"]
                g_config = GetEnv()
                db_location = g_config["db_location"]
                event_file = db_location + active_event_file[0]["db_file"] + ".sqlite"
                
                new_retry_entry = RetryEntries(
                    cid=cid, 
                    title=active_title_heat, 
                    driver_name=get_active_driver_name(event_file, cid)
                )
                db.session.add(new_retry_entry)
                db.session.commit()
            
        retry_entries = db.session.query(RetryEntries).filter(RetryEntries.title == active_title_heat).all()
        retry_entries_list = []
        for a in retry_entries:
            retry_entries_list.append({
                "CID": a.cid,
                "title": a.title,
                "driver_name": a.driver_name
            })

        # Emit to socket room
        emit_to_room(socketio, json.dumps(retry_entries_list), SOCKET_ROOMS['retry_notifications'])
        return retry_entries_list
    
    @api_bp.route('/api/toggle_retry', methods=['GET'])
    def toggle_retry():
        driver = request.args.get('driver', default=None, type=str)
        operation = request.args.get('operation', default=None, type=str)

        g_config = GetEnv()
        DB_PATH = "site.db"

        if str(driver) == "1":
            query = "SELECT D1 FROM active_drivers;"
        else:
            query = "SELECT D2 FROM active_drivers;"

        with sqlite3.connect(DB_PATH) as con:
            cur = con.cursor()
            active_driver = cur.execute(query).fetchall()

        if operation == "add":
            payload = json.dumps({
                "method": "add",
                "cid": active_driver[0][0]
            })
        else:
            payload = json.dumps({
                "method": "remove",
                "cid": active_driver[0][0]
            })

        url = "http://192.168.1.50:7777/api/retry_entries"
        headers = {'Content-Type': 'application/json'}
        response = requests.request("POST", url, headers=headers, data=payload)
        
        return {"status": "success", "message": "Changed state"}
    
    @api_bp.route('/api/set_active_driver_to_next', methods=['GET'])
    def set_active_driver_to_next():
        current_startlist = get_active_startlist()
        current_startlist_json = json.loads(current_startlist)
        active = False

        for k, a in enumerate(current_startlist_json):
            if k == 0:
                mode = a["race_config"]["MODE"]
            else:
                if mode == 0:
                    if active == True:
                        Set_active_driver(cid_1=a["drivers"][0]["id"])
                        event_data = get_active_startlist()
                        
                        # Import the send_data_to_room function
                        from app.views.api_view import send_data_to_room
                        send_data_to_room(event_data)
                        
                        requests.get("http://127.0.0.1:7777/api/active_event_update")
                        return {"status": "success", "message": "Driver set"}
                    
                    if a["drivers"][0]["active"] == True:
                        if (int(a["drivers"][0]["time_info"]["FINISHTIME"]) != 0 or 
                            int(a["drivers"][0]["time_info"]["PENELTY"]) != 0):
                            active = True

        return {"status": "error", "message": "No next driver found"}