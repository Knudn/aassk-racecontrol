# app/api/timedata_routes.py
from flask import request, current_app
import sqlite3
import json
import re
from app.lib.db_operation import get_active_event
from app.lib.utils import GetEnv, get_active_driver_name
from app.models import Session_Race_Records, ActiveEvents, MicroServices
from app import db, socketio
from sqlalchemy import func, desc
import requests
from app.config.websocket_config import emit_to_room, SOCKET_ROOMS

def register_timedata_routes(api_bp):
    """Register all timedata-related routes with the API blueprint"""
    
    @api_bp.route('/api/get_timedata/', methods=['GET'])
    def get_timedata():
        def format_db_rsp(a):
            return {
                "first_name": a.first_name,
                "last_name": a.last_name,
                "title_1": a.title_1,
                "title_2": a.title_2,
                "heat": a.heat,
                "finishtime": a.finishtime,
                "snowmobile": a.snowmobile,
                "penalty": a.penalty
            }

        events = request.args.get('events', default='False', type=str)
        heat = request.args.get('heat', default=None, type=str)
        title_1 = request.args.get('title_1', default=None, type=str)
        title_2 = request.args.get('title_2', default=None, type=str)
        single_all = request.args.get('single_all', default='false', type=str)
        entries_per_filter = request.args.get('entries_per_filter', default=1, type=int)
        unique_names = request.args.get('unique_names', default='false', type=str).lower() == 'true'
        ignore_penalty = request.args.get('ignore_penalty', default='false', type=str).lower() == 'true'

        if heat and heat.isdigit():
            heat = int(heat)

        event_data = {}

        if single_all != 'false':
            filter_combinations = [
                ('title_1', title_1),
                ('title_2', title_2),
                ('heat', heat),
                ('title_1+title_2', (title_1, title_2)),
                ('title_1+title_2+heat', (title_1, title_2, heat))
            ]

            for combo_name, filters in filter_combinations:
                query = Session_Race_Records.query

                if isinstance(filters, tuple):
                    if 'title_1' in combo_name and title_1:
                        query = query.filter(Session_Race_Records.title_1 == title_1)
                    if 'title_2' in combo_name and title_2:
                        query = query.filter(Session_Race_Records.title_2 == title_2)
                    if 'heat' in combo_name and heat:
                        query = query.filter(Session_Race_Records.heat == heat)
                else:
                    if combo_name == 'title_1' and title_1:
                        query = query.filter(Session_Race_Records.title_1 == title_1)
                    elif combo_name == 'title_2' and title_2:
                        query = query.filter(Session_Race_Records.title_2 == title_2)
                    elif combo_name == 'heat' and heat:
                        query = query.filter(Session_Race_Records.heat == heat)

                query = query.filter(Session_Race_Records.finishtime != 0)
                query = query.filter(Session_Race_Records.penalty == 0)

                if unique_names:
                    subquery = query.with_entities(
                        Session_Race_Records.first_name,
                        Session_Race_Records.last_name,
                        func.min(Session_Race_Records.finishtime).label('min_finishtime')
                    ).group_by(
                        Session_Race_Records.first_name, 
                        Session_Race_Records.last_name
                    ).subquery()

                    query = Session_Race_Records.query.join(
                        subquery,
                        (Session_Race_Records.first_name == subquery.c.first_name) &
                        (Session_Race_Records.last_name == subquery.c.last_name) &
                        (Session_Race_Records.finishtime == subquery.c.min_finishtime)
                    )

                query = query.order_by(Session_Race_Records.finishtime.asc())
                query = query.limit(entries_per_filter)

                records = query.all()
                for i, record in enumerate(records):
                    event_data[f"{combo_name}_{i}"] = format_db_rsp(record)

        else:
            query = Session_Race_Records.query

            if heat:
                query = query.filter(Session_Race_Records.heat == heat)
            if title_1:
                query = query.filter(Session_Race_Records.title_1 == title_1)
            if title_2:
                query = query.filter(Session_Race_Records.title_2 == title_2)

            query = query.filter(Session_Race_Records.finishtime != 0)

            if unique_names:
                subquery = query.with_entities(
                    Session_Race_Records.first_name,
                    Session_Race_Records.last_name,
                    func.min(Session_Race_Records.finishtime).label('min_finishtime')
                ).group_by(
                    Session_Race_Records.first_name, 
                    Session_Race_Records.last_name
                )

                query = Session_Race_Records.query.join(
                    subquery.subquery(),
                    (Session_Race_Records.first_name == subquery.c.first_name) &
                    (Session_Race_Records.last_name == subquery.c.last_name) &
                    (Session_Race_Records.finishtime == subquery.c.min_finishtime)
                )

            query = query.order_by(Session_Race_Records.finishtime.asc())
            query = query.limit(entries_per_filter)

            event_order = query.all()

            for k, a in enumerate(event_order):
                event_data[k] = format_db_rsp(a)

        return event_data
    
    @api_bp.route('/api/get_timedata_cross/', methods=['GET'])
    def get_timedata_cross():
        query = Session_Race_Records.query
        query = query.order_by(Session_Race_Records.points.desc(), Session_Race_Records.finishtime.asc())

        title_combo = request.args.get('combined_title')
        if title_combo:
            query = query.filter((Session_Race_Records.title_1 + " " + Session_Race_Records.title_2).ilike(f"%{title_combo}%"))

        title_1 = request.args.get('title_1')
        if title_1:
            query = query.filter(Session_Race_Records.title_1.ilike(f"%{title_1}%"))

        title_2 = request.args.get('title_2')
        if title_2:
            query = query.filter(Session_Race_Records.title_2.ilike(f"%{title_2}%"))

        heat = request.args.get('heat')
        if heat:
            query = query.filter(Session_Race_Records.heat == heat)

        name = request.args.get('name')
        if name:
            query = query.filter(db.or_(
                db.and_(Session_Race_Records.first_name + " " + Session_Race_Records.last_name).ilike(f"%{name}%"),
                db.and_(Session_Race_Records.last_name + " " + Session_Race_Records.first_name).ilike(f"%{name}%")
            ))

        limit = request.args.get('limit', type=int)
        if limit:
            query = query.limit(limit)

        records = query.all()
        results = [
            {
                "id": record.id,
                "cid": record.cid,
                "first_name": record.first_name,
                "last_name": record.last_name,
                "title_1": record.title_1,
                "title_2": record.title_2,
                "heat": record.heat,
                "finishtime": record.finishtime / 1_000,  # Convert to seconds
                "snowmobile": record.snowmobile,
                "penalty": record.penalty,
                "points": record.points
            } for record in records
        ]

        return results
    
    @api_bp.route('/api/driver-points', methods=['GET'])
    def get_driver_points():
        query = db.session.query(
            Session_Race_Records.first_name,
            Session_Race_Records.last_name,
            func.sum(Session_Race_Records.points).label('total_points'),
            func.min(
                db.case(
                    (Session_Race_Records.finishtime == 0, None),
                    (Session_Race_Records.penalty != 0, None),
                    else_=Session_Race_Records.finishtime
                )
            ).label('lowest_finishtime')
        ).group_by(
            Session_Race_Records.first_name,
            Session_Race_Records.last_name
        ).order_by(
            func.sum(Session_Race_Records.points).desc(),
            db.case(
                (func.min(
                    db.case(
                        (Session_Race_Records.finishtime == 0, None),
                        (Session_Race_Records.penalty != 0, None),
                        else_=Session_Race_Records.finishtime
                    )
                ) == None, 1),
                else_=0
            ),
            func.min(
                db.case(
                    (Session_Race_Records.finishtime == 0, None),
                    (Session_Race_Records.penalty != 0, None),
                    else_=Session_Race_Records.finishtime
                )
            )
        )

        combined_title = request.args.get('combined_title')
        if combined_title:
            query = query.filter(
                (Session_Race_Records.title_1 + ' ' + Session_Race_Records.title_2) == combined_title
            )
        else:
            title_1 = request.args.get('title_1')
            if title_1:
                query = query.filter(Session_Race_Records.title_1.ilike(f"%{title_1}%"))

            title_2 = request.args.get('title_2')
            if title_2:
                query = query.filter(Session_Race_Records.title_2.ilike(f"%{title_2}%"))

        heat = request.args.get('heat')
        if heat:
            query = query.filter(Session_Race_Records.heat == heat)

        name = request.args.get('name')
        if name:
            query = query.filter(db.or_(
                (Session_Race_Records.first_name + " " + Session_Race_Records.last_name).ilike(f"%{name}%"),
                (Session_Race_Records.last_name + " " + Session_Race_Records.first_name).ilike(f"%{name}%")
            ))

        results = query.all()
        output = [
            {
                "first_name": result.first_name,
                "last_name": result.last_name,
                "total_points": result.total_points,
                "lowest_finishtime": result.lowest_finishtime / 1_000 if result.lowest_finishtime else None  # Convert microseconds to seconds
            } for result in results
        ]

        return output
    
    @api_bp.route('/api/submit_timestamp_clock', methods=['POST'])
    def submit_timestamp_clock():
        g_config = GetEnv()
        db_location = g_config["db_location"]
        DB_PATH = "site.db"

        active_event_file = get_active_event()
        query = db.session.query(ActiveEvents.event_name, ActiveEvents.run, ActiveEvents.mode).filter(
            ActiveEvents.event_file == active_event_file[0]["db_file"]
        )

        active_event = query.first()
        event_title = active_event.event_name
        heat = active_event.run

        pattern = r"(\d{4}_\d{4})_(\d{2})_(\d{2}:\d{2}:\d{2}\.\d{3})_\d{5}"
        
        timestamp_raw = request.json["timestamp"]
        button = request.json["button"]

        match = re.match(pattern, timestamp_raw)

        if active_event.mode == 0:
            query = "SELECT D1 FROM active_drivers;"
        else:
            query = "SELECT D1, D2 FROM active_drivers;"

        with sqlite3.connect(DB_PATH) as con:
            cur = con.cursor()
            active_driver = cur.execute(query).fetchall()
        
        if match:
            device, id, timestamp = match.groups()
            current_app.logger.info(f"Device: {device}, ID: {id}, Timestamp: {timestamp}")
        else:
            current_app.logger.warning("No match found in timestamp format")

        current_timestamps = current_app.config.get('timestamp_tracket', [])

        if g_config.get("dual_start_manual_clock", False) == True:
            start_both = True
        else:
            start_both = False

        if len(current_timestamps) > 25:
            current_timestamps.pop(0)
            if button == 1 and start_both == True:
                current_timestamps.pop(0)

        if active_event.mode == 0:
            if button == 1:
                current_timestamps.append({
                    "id": len(current_timestamps) + 1, 
                    "TITLE": event_title, 
                    "HEAT": heat, 
                    "DRIVER": active_driver[0][0], 
                    "DRIVER_NAME": get_active_driver_name(db_location + active_event_file[0]["db_file"] + ".sqlite", active_driver[0][0]), 
                    "BUTTON": button,
                    "TS_SIMPLE": timestamp, 
                    "TS_RAW": timestamp_raw,
                    "PLACEMENT": "START"
                })
            if button == 3:
                current_timestamps.append({
                    "id": len(current_timestamps) + 1, 
                    "TITLE": event_title, 
                    "HEAT": heat, 
                    "DRIVER": active_driver[0][0], 
                    "DRIVER_NAME": get_active_driver_name(db_location + active_event_file[0]["db_file"] + ".sqlite", active_driver[0][0]), 
                    "BUTTON": button,
                    "TS_SIMPLE": timestamp, 
                    "TS_RAW": timestamp_raw,
                    "PLACEMENT": "FINISH"
                })
        else:
            if button == 1 and start_both == False:
                current_timestamps.append({
                    "id": len(current_timestamps) + 1, 
                    "TITLE": event_title, 
                    "HEAT": heat, 
                    "DRIVER": active_driver[0][0], 
                    "DRIVER_NAME": get_active_driver_name(db_location + active_event_file[0]["db_file"] + ".sqlite", active_driver[0][0]), 
                    "BUTTON": button,
                    "TS_SIMPLE": timestamp, 
                    "TS_RAW": timestamp_raw,
                    "PLACEMENT": "START"
                })
            elif button == 1 and start_both == True:
                current_timestamps.append({
                    "id": len(current_timestamps) + 1, 
                    "TITLE": event_title, 
                    "HEAT": heat, 
                    "DRIVER": active_driver[0][0], 
                    "DRIVER_NAME": get_active_driver_name(db_location + active_event_file[0]["db_file"] + ".sqlite", active_driver[0][0]), 
                    "BUTTON": button,
                    "TS_SIMPLE": timestamp, 
                    "TS_RAW": timestamp_raw,
                    "PLACEMENT": "START"
                })
                current_timestamps.append({
                    "id": len(current_timestamps) + 1, 
                    "TITLE": event_title, 
                    "HEAT": heat, 
                    "DRIVER": active_driver[0][1], 
                    "DRIVER_NAME": get_active_driver_name(db_location + active_event_file[0]["db_file"] + ".sqlite", active_driver[0][1]), 
                    "BUTTON": button,
                    "TS_SIMPLE": timestamp, 
                    "TS_RAW": timestamp_raw,
                    "PLACEMENT": "START"
                })
            elif button == 2 and start_both == False:
                current_timestamps.append({
                    "id": len(current_timestamps) + 1, 
                    "TITLE": event_title, 
                    "HEAT": heat, 
                    "DRIVER": active_driver[0][1], 
                    "DRIVER_NAME": get_active_driver_name(db_location + active_event_file[0]["db_file"] + ".sqlite", active_driver[0][1]), 
                    "BUTTON": button,
                    "TS_SIMPLE": timestamp, 
                    "TS_RAW": timestamp_raw,
                    "PLACEMENT": "START"
                })
            elif button == 3:
                current_timestamps.append({
                    "id": len(current_timestamps) + 1, 
                    "TITLE": event_title, 
                    "HEAT": heat, 
                    "DRIVER": active_driver[0][0], 
                    "DRIVER_NAME": get_active_driver_name(db_location + active_event_file[0]["db_file"] + ".sqlite", active_driver[0][0]), 
                    "BUTTON": button,
                    "TS_SIMPLE": timestamp, 
                    "TS_RAW": timestamp_raw,
                    "PLACEMENT": "FINISH"
                })
            elif button == 4:
                current_timestamps.append({
                    "id": len(current_timestamps) + 1, 
                    "TITLE": event_title, 
                    "HEAT": heat, 
                    "DRIVER": active_driver[0][1],
                    "DRIVER_NAME": get_active_driver_name(db_location + active_event_file[0]["db_file"] + ".sqlite", active_driver[0][1]), 
                    "BUTTON": button,
                    "TS_SIMPLE": timestamp, 
                    "TS_RAW": timestamp_raw,
                    "PLACEMENT": "FINISH"
                })
        
        # Update the config
        current_app.config['timestamp_tracket'] = current_timestamps

        if g_config.get("auto_commit_manual_clock", False) == True:
            send_fixed_timestamp(timestamp_raw)

        # Emit to socket room
        emit_to_room(socketio, current_timestamps, SOCKET_ROOMS['clock_management'])

        return {"status": "success", "message": "Timestamp submitted"}


def send_fixed_timestamp(timestamp):
    clock_server_endpoint = db.session.query(MicroServices.params).filter(
        MicroServices.path == "clock_server_vola.py"
    ).first()[0]

    url = f'http://{clock_server_endpoint}:5000/send-timestamp'
    headers = {'Content-Type': 'application/json'}
    
    try:
        response = requests.post(url, headers=headers, data=json.dumps({"timestamp": timestamp}))
        
        if response.status_code == 200:
            return True
        else:
            current_app.logger.error(f"Error sending timestamp: {response.status_code}")
            return False
    except Exception as e:
        current_app.logger.error(f"Exception sending timestamp: {str(e)}")
        return False