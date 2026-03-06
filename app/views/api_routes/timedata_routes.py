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
            d = a.data or {}
            return {
                "first_name": d.get("first_name"),
                "last_name": d.get("last_name"),
                "title_1": d.get("title_1") or d.get("event_name"),
                "title_2": d.get("title_2") or a.title_2,
                "heat": a.heat,
                "finishtime": d.get("finishtime", 0),
                "snowmobile": d.get("snowmobile"),
                "penalty": d.get("penalty", 0)
            }

        def build_query(f_title_1=None, f_title_2=None, f_heat=None):
            # title_2 column = combined "title_1 title_2" for MSport, run_name for Orbits
            q = Session_Race_Records.query
            if f_title_1:
                q = q.filter(Session_Race_Records.title_1==f_title_1)
            if f_title_2:
                q = q.filter(Session_Race_Records.title_2==f_title_2)
            if f_heat:
                q = q.filter(Session_Race_Records.heat == f_heat)
            return q

        def post_filter_and_sort(records, skip_penalty=True):
            result = []
            for r in records:
                d = r.data or {}
                if skip_penalty:
                    if d.get("finishtime", 0) == 0:
                        continue
                    if d.get("penalty", 0) != 0:
                        continue

                result.append(r)
            
            result.sort(key=lambda r: (r.data or {}).get("finishtime", float('inf')))
            return result

        def deduplicate_by_name(records):
            seen = set()
            result = []
            for r in records:
                d = r.data or {}
                name_key = (d.get("first_name"), d.get("last_name"))
                if name_key not in seen:
                    seen.add(name_key)
                    result.append(r)
            return result

        heat = request.args.get('heat', default=None, type=str)
        title_1 = request.args.get('title_1', default=None, type=str)
        title_2 = request.args.get('title_2', default=None, type=str)
        single_all = request.args.get('single_all', default='false', type=str)
        entries_per_filter = request.args.get('entries_per_filter', default=1, type=int)
        unique_names = request.args.get('unique_names', default='false', type=str).lower() == 'true'
        ignore_penalty = request.args.get('ignore_penalty', default='false', type=str).lower() == 'true'

        if heat and str(heat).isdigit():
            heat = int(heat)

        event_data = {}
        skip_penalty = not ignore_penalty

        if single_all != 'false':
            filter_combinations = [
                ('title_1',            title_1, None,    None),
                ('title_2',            None,    title_2, None),
                ('heat',               None,    None,    heat),
                ('title_1+title_2',    title_1, title_2, None),
                ('title_1+title_2+heat', title_1, title_2, heat),
            ]

            for combo_name, f_t1, f_t2, f_heat in filter_combinations:
                records = build_query(f_t1, f_t2, f_heat).all()
                records = post_filter_and_sort(records, skip_penalty)
                if unique_names:
                    records = deduplicate_by_name(records)
                records = records[:entries_per_filter]
                for i, record in enumerate(records):
                    event_data[f"{combo_name}_{i}"] = format_db_rsp(record)
        else:
            records = build_query(title_1, title_2, heat).all()
            records = post_filter_and_sort(records, skip_penalty)
            if unique_names:
                records = deduplicate_by_name(records)
            records = records[:entries_per_filter]
            for k, a in enumerate(records):
                event_data[k] = format_db_rsp(a)

        return event_data
    
    @api_bp.route('/api/get_timedata_cross/', methods=['GET'])
    def get_timedata_cross():
        query = Session_Race_Records.query

        title_combo = request.args.get('combined_title')
        if title_combo:
            query = query.filter(Session_Race_Records.title_2.ilike(f"%{title_combo}%"))

        title_1 = request.args.get('title_1')
        if title_1:
            query = query.filter(Session_Race_Records.title_2.ilike(f"%{title_1}%"))

        title_2 = request.args.get('title_2')
        if title_2:
            query = query.filter(Session_Race_Records.title_2.ilike(f"%{title_2}%"))

        heat = request.args.get('heat')
        if heat:
            query = query.filter(Session_Race_Records.heat == heat)

        records = query.all()

        name = request.args.get('name')
        limit = request.args.get('limit', type=int)

        results = []
        for record in records:
            d = record.data or {}
            first = d.get("first_name", "")
            last = d.get("last_name", "")
            if name:
                n = name.lower()
                if n not in (first + " " + last).lower() and n not in (last + " " + first).lower():
                    continue
            results.append({
                "id": record.id,
                "cid": record.cid,
                "first_name": first,
                "last_name": last,
                "title_1": d.get("title_1") or d.get("event_name"),
                "title_2": d.get("title_2") or record.title_2,
                "heat": record.heat,
                "finishtime": d.get("finishtime", 0),
                "snowmobile": d.get("snowmobile"),
                "penalty": d.get("penalty", 0),
                "points": d.get("points", 0),
                "laps": d.get("laps", 0),
                "reaction": d.get("reaction", 0)
            })

        results.sort(key=lambda x: (-x["points"], x["finishtime"] if x["finishtime"] > 0 else float('inf')))

        if limit:
            results = results[:limit]

        return results
    
    @api_bp.route('/api/driver-points', methods=['GET'])
    def get_driver_points():
        combined_title = request.args.get('combined_title')
        title_1 = request.args.get('title_1')
        title_2 = request.args.get('title_2')
        heat = request.args.get('heat')
        name = request.args.get('name')

        query = Session_Race_Records.query
        if combined_title:
            query = query.filter(Session_Race_Records.title_2.ilike(f"%{combined_title}%"))
        else:
            if title_1:
                query = query.filter(Session_Race_Records.title_2.ilike(f"%{title_1}%"))
            if title_2:
                query = query.filter(Session_Race_Records.title_2.ilike(f"%{title_2}%"))
        if heat:
            query = query.filter(Session_Race_Records.heat == int(heat))

        records = query.all()

        entries = {}
        for rec in records:
            d = rec.data or {}
            first = d.get("first_name", "")
            last = d.get("last_name", "")
            if name:
                n = name.lower()
                if n not in (first + " " + last).lower() and n not in (last + " " + first).lower():
                    continue
            cid = rec.cid
            pts = d.get("points", 0) or 0
            ft = d.get("finishtime", 0) or 0
            penalty = d.get("penalty", 0) or 0
            valid_ft = ft if (ft > 0 and penalty == 0) else 0
            if cid not in entries:
                entries[cid] = {"first_name": first, "last_name": last, "points": 0, "lowest_finishtime": 0}
            entries[cid]["points"] += pts
            if valid_ft > 0 and (entries[cid]["lowest_finishtime"] == 0 or valid_ft < entries[cid]["lowest_finishtime"]):
                entries[cid]["lowest_finishtime"] = valid_ft

        sorted_entries = sorted(
            entries.values(),
            key=lambda e: (-e["points"], e["lowest_finishtime"] if e["lowest_finishtime"] > 0 else float('inf'))
        )

        output = [
            {
                "first_name": e["first_name"],
                "last_name": e["last_name"],
                "total_points": e["points"],
                "lowest_finishtime": e["lowest_finishtime"] / 1000 if e["lowest_finishtime"] else None
            }
            for e in sorted_entries
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