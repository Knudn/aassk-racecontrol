# app/api/event_routes.py
from flask import request, current_app
import sqlite3
from app.lib.db_operation import (
    reload_event as reload_event_func,
    update_active_event_stats,
    get_active_startlist,
    get_active_startlist_w_timedate,
    get_specific_event_data,
    get_active_event
)
from app.lib.utils import (
    intel_sort,
    update_info_screen,
    export_events,
    GetEnv
)
from app.models import (
    ActiveEvents,
    Session_Race_Records,
    archive_server
)
from app import db, socketio
from sqlalchemy import func
import requests
import json
import random
from app.config.websocket_config import emit_to_room, SOCKET_ROOMS

def register_event_routes(api_bp):
    """Register all event-related routes with the API blueprint"""
    
    # Event data endpoints
    @api_bp.route('/api/get_current_startlist', methods=['GET'])
    def get_current_startlist():
        return get_active_startlist()
    
    @api_bp.route('/api/active_event_update', methods=['GET'])
    def active_event_update():
        list_address = current_app.config['listen_address']
        if str(list_address) == "0.0.0.0":
            list_address = "localhost"
        update_active_event_stats()

        event_data = get_active_startlist()
        if current_app.config['event_content'] != event_data:
            # Import the send_data_to_room function from parent module
            from app.views.api_view import send_data_to_room
            send_data_to_room(event_data)
            
            current_app.config['event_content'] = event_data
        remote_server_state = archive_server.query.first()

        if remote_server_state.enabled:
            requests.get(f'http://{list_address}:7777/api/upate_remote_data?type=single')

        return {"status": "success", "message": "Event data updated"}
    
    @api_bp.route('/api/update_active_startlist', methods=['GET'])
    def update_active_startlist():
        return {"error": "Method not allowed"}, 405
    
    @api_bp.route('/api/export', methods=['GET'])
    def export():
        events = request.args.get('events', default=None)
        event_file = request.args.get('event_file', default=None)

        if event_file:
            return export_events(event_file=event_file)
            
        if events == 'all':
            return export_events()
        elif events == 'active':
            return get_active_startlist_w_timedate()
        else:
            return {'error': 'No events parameter provided'}, 400
    
    @api_bp.route('/api/get_current_startlist_w_data', methods=['GET'])
    def get_current_startlist_w_data():
        upcoming = request.args.get('upcoming')
        event = request.args.get('event')
        heat = request.args.get('heat')
        event_comb = request.args.get('event_comb')

        if event_comb is not None:
            events = []
            active_event_current = get_active_event()
            query = db.session.query(ActiveEvents.event_file, ActiveEvents.run).distinct().filter(
                        ActiveEvents.event_name.like(f"%{event_comb}%")).all()

            for a in query:
                events.append([{'db_file': a.event_file, 'SPESIFIC_HEAT': a.run}])

            return get_active_startlist_w_timedate(event_comb=events)

        if upcoming is not None:
            if upcoming.lower() == "true":
                return get_active_startlist_w_timedate(upcoming=True)
        
        if event is not None:
            query = db.session.query(ActiveEvents.event_file, ActiveEvents.run, ActiveEvents.mode).filter(
                ActiveEvents.event_name == event, ActiveEvents.run == heat
            ).first()

            event = [{'db_file': query.event_file, 'SPESIFIC_HEAT': query.run}]
            return get_active_startlist_w_timedate(event_wl=event)
        
        return get_active_startlist_w_timedate()
    
    @api_bp.route('/api/get_current_startlist_w_data_loop', methods=['GET'])
    def get_current_startlist_w_data_loop():
        event_filter = request.args.get('filter', default='', type=str)
        heat = request.args.get('heat', default='', type=str)
        latest = request.args.get('latest', default='', type=str)
        finished = request.args.get('finished', default='', type=str)

        g_config = GetEnv()

        session_index = request.cookies.get('session_index', '0')
        try:
            session_index = int(session_index) + 1
        except ValueError:
            session_index = 0
        
        query = db.session.query(
            Session_Race_Records.id,
            Session_Race_Records.first_name,
            Session_Race_Records.last_name,
            Session_Race_Records.title_1,
            Session_Race_Records.title_2,
            Session_Race_Records.heat,
            Session_Race_Records.finishtime,
            Session_Race_Records.snowmobile,
            Session_Race_Records.penalty
        ).group_by(
            Session_Race_Records.title_1, Session_Race_Records.title_2, Session_Race_Records.heat
        ).having(
            Session_Race_Records.heat == func.max(Session_Race_Records.heat)
        )

        if finished != "true":
            query = query.filter(
                Session_Race_Records.finishtime == 0
            ).filter(
                Session_Race_Records.penalty == 0
            )
        else:
            query = query.filter(Session_Race_Records.finishtime != 0)

        if event_filter != "":
            query = query.filter((Session_Race_Records.title_1 + " " + Session_Race_Records.title_2).like(f'%{event_filter}%'))

        results = query.all()

        entries = []

        for a in results:
            if a.title_1 + " " + a.title_2 not in entries:
                entries.append(a.title_1 + " " + a.title_2)

        max_len = len(entries)
        if max_len == 0:
            return {"error": "No entries found"}, 404
            
        if max_len <= session_index:
            session_index = 0
            
        title_combo = entries[session_index]

        query = db.session.query(ActiveEvents.event_file, ActiveEvents.run, ActiveEvents.mode).filter(
            ActiveEvents.event_name == title_combo
        )

        all_events = query.all()
        event_file = all_events[0][0]
        heat = 0

        for a in results:
            if a.title_1 + " " + a.title_2 == title_combo:
                if heat == 0:
                    heat = a.heat
                if latest != "":
                    if heat < a.heat:
                        heat = a.heat
                else:
                    if heat > a.heat:
                        heat = a.heat

        event = [{"SPESIFIC_HEAT": heat, "db_file": g_config["db_location"] + event_file + ".sqlite"}]
        response = get_active_startlist_w_timedate(event_wl=event)
        
        # Set cookie for session index
        resp = current_app.make_response(response)
        resp.set_cookie('session_index', str(session_index))
        return resp
    
    @api_bp.route('/api/get_specific_event_data_loop', methods=['GET'])
    def get_specific_event_data_loop():
        session_index = request.cookies.get('session_index', '0')
        try:
            session_index = int(session_index) + 1
        except ValueError:
            session_index = 0

        query = db.session.query(
            Session_Race_Records.id,
            Session_Race_Records.first_name,
            Session_Race_Records.last_name,
            Session_Race_Records.title_1,
            Session_Race_Records.title_2,
            Session_Race_Records.heat,
            Session_Race_Records.finishtime,
            Session_Race_Records.snowmobile,
            Session_Race_Records.penalty
        ).filter(
            (Session_Race_Records.title_1 + " " + Session_Race_Records.title_2).like(f'%Stige%')
        ).filter(
            Session_Race_Records.finishtime != 0
        ).group_by(
            Session_Race_Records.title_1, Session_Race_Records.title_2
        ).having(
            Session_Race_Records.heat == func.max(Session_Race_Records.heat)
        )

        # Execute the query to get the results
        results = query.all()
        max_len = len(results)
        if max_len == 0:
            return {"error": "No entries found"}, 404
            
        if max_len <= session_index:
            session_index = 0

        event_int = session_index
        heat = []
        title_combo = results[event_int][3] + " " + results[event_int][4]

        query = db.session.query(ActiveEvents.event_file, ActiveEvents.run, ActiveEvents.mode).filter(
            ActiveEvents.event_name == title_combo
        )  

        results = query.all()
        heat_insert = ""
        event_mode = results[0][2]
        if heat_insert == '':
            for a in results:
                heat.append(a[1])
        elif heat_insert == "latest":
            for a in results:
                heat.append(a[1])
        else:
            heat.append(heat_insert)

        event = [{'db_file': results[0][0], "SPESIFIC_HEAT": heat}]
        
        response = {"Timedata": get_specific_event_data(event_filter=event), "event_data": [title_combo, event_mode]}
        resp = current_app.make_response(response)
        resp.set_cookie('session_index', str(session_index))
        return resp
    
    @api_bp.route('/api/get_specific_event_data', methods=['GET'])
    def get_specific_event_data_view():
        event_filter = request.args.get('event_filter', default='', type=str)
        heat_insert = request.args.get('heat', default='', type=str)

        session_index = request.cookies.get('session_index', '0')
        try:
            session_index = int(session_index) + 1
        except ValueError:
            session_index = 0
        
        if event_filter == "":
            active_event = get_active_event()
            try:
                event_filter = db.session.query(ActiveEvents.event_name).filter(
                    ActiveEvents.event_file == active_event[0]["db_file"]
                ).first()[0]
            except Exception as e:
                current_app.logger.error(f"No active event: {str(e)}")
        
        query = db.session.query(
            Session_Race_Records.id,
            Session_Race_Records.first_name,
            Session_Race_Records.last_name,
            Session_Race_Records.title_1,
            Session_Race_Records.title_2,
            Session_Race_Records.heat,
            Session_Race_Records.finishtime,
            Session_Race_Records.snowmobile,
            Session_Race_Records.penalty
        ).filter(
            (Session_Race_Records.title_1 + " " + Session_Race_Records.title_2).like(f'%{event_filter}%')
        ).group_by(
            Session_Race_Records.title_1, Session_Race_Records.title_2
        ).having(
            Session_Race_Records.heat == func.max(Session_Race_Records.heat)
        )

        # Execute the query to get the results
        results = query.all()
        max_len = len(results)
        
        if max_len == 0:
            return {"error": "No entries found"}, 404
        
        event_int = random.randint(0, max_len-1)
        heat = []
        title_combo = results[event_int][3] + " " + results[event_int][4]

        query = db.session.query(ActiveEvents.event_file, ActiveEvents.run, ActiveEvents.mode).filter(
            ActiveEvents.event_name == title_combo
        )  

        results = query.all()
        
        if heat_insert == '':
            for a in results:
                heat.append(a[1])
        elif heat_insert == "latest":
            for a in results:
                heat.append(a[1])
        else:
            heat.append(heat_insert)

        event_mode = results[0][2]

        event = [{'db_file': results[0][0], "SPESIFIC_HEAT": heat}]

        return {"Timedata": get_specific_event_data(event_filter=event), "event_data": [title_combo, event_mode]}
    
    @api_bp.route('/api/get_event_order', methods=['GET'])
    def get_event_order():
        event_order = ActiveEvents.query.order_by(ActiveEvents.sort_order).all()
        current_active_event = get_active_event()[0]

        data = []
        
        for a in event_order:
            state = (str(a.event_file) == str(current_active_event["db_file"]) and 
                    str(current_active_event["SPESIFIC_HEAT"]) == str(a.run))
            
            data.append({
                "Order": a.sort_order, 
                "Event": a.event_name, 
                "Enabled": a.enabled, 
                "Heat": a.run, 
                "Active": state
            })
        
        return data
    
    @api_bp.route('/api/update_event', methods=['POST'])
    def update_event():
        g_config = GetEnv()
        active_event = get_active_event()
        
        if request.form.get('event_file') == "active_event":
            active_event = get_active_event()
            selectedEventFile = active_event[0]["db_file"]
            selectedRun = active_event[0]["SPESIFIC_HEAT"]
        else:
            selectedEventFile = request.form.get('single_event')
            
        sync_state = request.form.get('sync')

        if sync_state == "true":
            event_name = request.form.get('event_name')

            # Delete local driver session entries for the specific event
            db.session.query(Session_Race_Records).filter(
                (Session_Race_Records.title_1 + " " + Session_Race_Records.title_2) == event_name
            ).delete()
            db.session.commit()
            # Note: full_db_reload function needs to be imported or defined
            # full_db_reload(add_intel_sort=False, Event=selectedEventFile)

        db_location = g_config.get("db_location", "")
        
        try:
            with sqlite3.connect(db_location + selectedEventFile + ".sqlite") as con:
                cur = con.cursor()
                cur.execute("SELECT COUNT() FROM drivers;")
                amount_drivers = cur.fetchone()[0]
                cur.execute("SELECT COUNT() FROM sqlite_master WHERE type='table' AND name LIKE 'driver\_%' ESCAPE '\\';")
                heat_num = cur.fetchone()[0]
                valid_recorded_times = 0
                invalid_recorded_times = 0
                drivers_left = 0

                for a in range(1, heat_num+1):
                    cur.execute("SELECT COUNT() FROM driver_stats_r{0} WHERE FINISHTIME != 0 AND PENELTY = 0;".format(a))
                    valid_recorded_times += cur.fetchone()[0]

                    cur.execute("SELECT COUNT() FROM driver_stats_r{0} WHERE PENELTY != 0;".format(a))
                    invalid_recorded_times += cur.fetchone()[0]

                    cur.execute("SELECT COUNT() FROM driver_stats_r{0} WHERE FINISHTIME = 0 AND PENELTY = 0;".format(a))
                    drivers_left += cur.fetchone()[0]

                event_config = {
                    "all_records": (valid_recorded_times + invalid_recorded_times + drivers_left), 
                    "p_times": invalid_recorded_times, 
                    "v_times": valid_recorded_times, 
                    "l_times": drivers_left, 
                    "drivers": amount_drivers, 
                    "heats": heat_num
                }
                return event_config
        except Exception as e:
            current_app.logger.error(f"Error updating event: {str(e)}")
            return {"error": f"Failed to update event: {str(e)}"}, 500
    
    @api_bp.route('/api/reload_event', methods=['POST'])
    def reload_event():
        data = request.json
        reload_event_func(data["file"], data["run"])
        return {"status": "success", "message": "Event reloaded", "data": data}
    
    @api_bp.route('/api/get_kavli_crit', methods=['GET'])
    def get_kavli_crit():
        from app.models import EventKvaliRate
        
        kvali_criteria = [event.to_dict() for event in EventKvaliRate.query.all()]
        return kvali_criteria