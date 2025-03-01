import app.config
from flask import Blueprint, request, send_from_directory, session
import sqlite3
from app.lib.db_operation import reload_event as reload_event_func
from app.lib.db_operation import update_active_event_stats, get_active_startlist, get_active_startlist_w_timedate, get_specific_event_data
from app import socketio
from app.lib.utils import intel_sort, update_info_screen, export_events, GetEnv
from sqlalchemy import func

api_bp = Blueprint('api', __name__)


@api_bp.route('/api/check_remote_heartbeat/', methods=['GET'])
def check_remote_heartbeat():
    from app.models import archive_server
    import requests


    microservices = archive_server.query.first()
    url = f"http://{microservices.hostname}/heartbeat"
    response = requests.get(url)

    if response.status_code == 200:
        return "OK"
    else:
        return "ERROR"

@api_bp.route('/api/start_status', methods=['GET', 'POST'])
def start_status():
    import requests
    from flask import current_app

    if request.method == "POST":
        data = request.get_json()
        current_app.config['start_list_state'] = data
        return "Updated"
    else:
        try:
            with sqlite3.connect("site.db") as con:
                query = "SELECT D1, D2 FROM active_drivers;"
                cur = con.cursor()
                active_driver = cur.execute(query).fetchall()
                D1 = active_driver[0][0]
                D2 = active_driver[0][1]

                for a in current_app.config['start_list_state']:
                    print(a)
                    if int(D1) == int(a["CID"]) and a["STATUS"] == "STARTED":
                        return "STARTED"
                    elif int(D2) == int(a["CID"]) and a["STATUS"] == "STARTED":
                        return "STARTED"

                return "FINISHED"
                
            return current_app.config['start_list_state']
        except:
            return []
        


@api_bp.route('/api/init', methods=['POST'])
def receive_init():
    from app.models import InfoScreenInitMessage
    from app import db
    import hashlib

    data = request.json
    hostname = data.get('Hostname')
    ip = request.remote_addr
    id_hash = hashlib.md5((str(ip)+str(hostname)).encode()).hexdigest()[-5:]

    existing_message = InfoScreenInitMessage.query.filter_by(unique_id=id_hash).first()

    if existing_message:
        return {"Added":id_hash, "Approved": existing_message.approved}
    else:
        new_message = InfoScreenInitMessage(hostname=hostname, ip=ip, unique_id=id_hash)
        db.session.add(new_message)
        db.session.commit()

        return {"Added":id_hash, "Approved": False}

        
@api_bp.route('/api/infoscreen_asset/<filename>')
def infoscreen_asset(filename):
    return send_from_directory('static/assets/infoscreen', filename)

@api_bp.route('/api/send_data')
def send_data_to_room(msg):
    room = request.args.get('room')
    socketio.emit('response', msg, room="room1")
    return {"message": "Data sent to the room"}

@api_bp.route('/api/update_active_drivers', methods=['GET','POST'])
def update_active_drivers():
    from app.models import ActiveDrivers
    from app import db
    
    if request.method == 'POST':
        return request.json
    else:
        return "Method not allowed"

@api_bp.route('/api/active_event_update', methods=['GET'])
def active_event_update():
    from flask import current_app
    import requests
    from app.models import archive_server
    import json

    list_address = current_app.config['listen_address']
    if str(list_address) == "0.0.0.0":
        list_address = "localhost"
    update_active_event_stats()

    event_data = get_active_startlist()
    if current_app.config['event_content'] != event_data:
        send_data_to_room(event_data)
        
        current_app.config['event_content'] = event_data
    remote_server_state = archive_server.query.first()

    if remote_server_state.enabled:
        requests.get('http://{0}:7777/api/upate_remote_data?type=single'.format(list_address))

    return "Updated"

@api_bp.route('/api/update_active_startlist', methods=['GET'])
def update_active_startlist():
    return "Method not allowed"

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
        return 'No events parameter provided'

@api_bp.route('/api/get_current_startlist', methods=['GET'])
def get_current_startlist():

    return get_active_startlist()

@api_bp.route('/api/upate_remote_data', methods=['GET'])
def upate_remote_data():
    from app.models import archive_server, EventKvaliRate, ActiveEvents
    import requests
    import json
    from app.lib.utils import export_events
    import app

    update_type = request.args.get('type', type=str)

    archive_server_data = archive_server.query.first()

    if archive_server_data:
        password = archive_server_data.auth_token
        hostname = archive_server_data.hostname

    if update_type == "single":
        send_data = get_active_startlist_w_timedate()
        single_event = True
        result = None
        event_data = None

    elif update_type == "full_sync":
        from app.models import Session_Race_Records

        title_1_filter = Session_Race_Records.query.first().title_1
        event_data = []

        single_event = False
        data = EventKvaliRate.query.all()
        events = ActiveEvents.query.filter(ActiveEvents.enabled == 1).order_by(ActiveEvents.sort_order).all()
        for k, a in enumerate(events):
            event_data.append({"order":k, "event_name":a.event_name.replace(title_1_filter, ""), "run":a.run, "mode":a.mode})

        result = [event.to_dict() for event in data]
        send_data = export_events()

    data = {"token":password,
            "data":send_data,
            "single_event":single_event,
            "kvali_ranking":json.dumps(result),
            "event_data":json.dumps(event_data)
            }

    requests.post(f"http://{hostname}/api/realtime_data", json=data)
    return get_active_startlist_w_timedate()


@api_bp.route('/api/get_current_startlist_w_data', methods=['GET'])
def get_current_startlist_w_data():
    from app.models import Session_Race_Records, ActiveEvents
    from app import db
    

    upcoming = request.args.get('upcoming')
    event = request.args.get('event')
    heat = request.args.get('heat')
    event_comb = request.args.get('event_comb')

    if event_comb != None:
        from app.lib.db_operation import get_active_event
        events = []
        active_event_current = get_active_event()
        #event_comb should be equal to TITLE_2
        query = db.session.query(ActiveEvents.event_file, ActiveEvents.run).distinct().filter(
                    ActiveEvents.event_name.like(f"%{event_comb}%")).all()

        for a in query:
            events.append([{'db_file':a.event_file, 'SPESIFIC_HEAT':a.run}])

        return get_active_startlist_w_timedate(event_comb=events)

    if upcoming != None:
        if upcoming.lower() == "true":
            return get_active_startlist_w_timedate(upcoming=True)
    
    if event != None:

        query = db.session.query(ActiveEvents.event_file, ActiveEvents.run, ActiveEvents.mode).filter(
            ActiveEvents.event_name == event, ActiveEvents.run == heat
        ).first()

        event = [{'db_file':query.event_file, 'SPESIFIC_HEAT':query.run}]
        return get_active_startlist_w_timedate(event_wl=event)
    
    return get_active_startlist_w_timedate()

@api_bp.route('/api/update_event', methods=['POST'])
def update_event():
        from app.lib.db_operation import get_active_event
        from app.lib.utils import GetEnv
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

            #Delete local driver session entries for the spesific event
            db.session.query(Session_Race_Records).filter((Session_Race_Records.title_1 + " " + Session_Race_Records.title_2)==event_name).delete()
            db.session.commit()
            full_db_reload(add_intel_sort=False, Event=selectedEventFile)


        print("Getting:", selectedEventFile)
        

        with sqlite3.connect(db_location + selectedEventFile + ".sqlite") as con:
            cur = con.cursor()
            cur.execute(f"SELECT COUNT() FROM drivers;")
            amount_drivers = cur.fetchone()
            cur.execute(f"SELECT COUNT() FROM sqlite_master WHERE type='table' AND name LIKE 'driver\_%' ESCAPE '\\';")
            heat_num = cur.fetchone()[0]
            valid_recorded_times = 0
            invalid_recorded_times = 0
            drivers_left = 0

            for a in range(1,heat_num+1):
                cur.execute("SELECT COUNT() FROM driver_stats_r{0} WHERE FINISHTIME != 0 AND PENELTY = 0;".format(a))
                valid_recorded_times += cur.fetchone()[0]

                cur.execute("SELECT COUNT() FROM driver_stats_r{0} WHERE PENELTY != 0;".format(a))
                invalid_recorded_times += cur.fetchone()[0]

                cur.execute("SELECT COUNT() FROM driver_stats_r{0} WHERE FINISHTIME = 0 AND PENELTY = 0;".format(a))
                drivers_left += cur.fetchone()[0]

            event_config = {"all_records":(valid_recorded_times + invalid_recorded_times + drivers_left), "p_times":invalid_recorded_times, "v_times":valid_recorded_times, "l_times":drivers_left, "drivers":amount_drivers, "heats":heat_num}
            return event_config
        

@api_bp.route('/api/get_current_startlist_w_data_loop', methods=['GET'])
def get_current_startlist_w_data_loop():

    from app.models import Session_Race_Records, ActiveEvents
    import random
    from app import db
    from app.lib.db_operation import get_active_event

    event_filter = request.args.get('filter', default='', type=str)
    heat = request.args.get('heat', default='', type=str)
    latest = request.args.get('latest', default='', type=str)
    finished = request.args.get('finished', default='', type=str)


    g_config = GetEnv()

    session['index'] = session.get('index', 0) + 1
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
        return "None"
    if max_len <= session['index']:
        session['index'] = 0
        
    title_combo = entries[session['index']]

    query = db.session.query(ActiveEvents.event_file, ActiveEvents.run, ActiveEvents.mode).filter(
        ActiveEvents.event_name == title_combo
    )

    all = query.all()
    event_file = all[0][0]
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


    event_db_file = (g_config["db_location"]+event_file+".sqlite")
    event = [{"SPESIFIC_HEAT":heat, "db_file":event_db_file}]
    return get_active_startlist_w_timedate(event_wl=event)



@api_bp.route('/api/get_specific_event_data_loop', methods=['GET'])
def get_specific_event_data_loop():

    from app.models import Session_Race_Records, ActiveEvents
    import random
    from app import db
    from app.lib.db_operation import get_active_event

    session['index'] = session.get('index', 0) + 1

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
    #Not sure why i added this filter
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
        return "None"
    if max_len <= session['index']:
        session['index'] = 0


    event_int = session['index']
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

    event = [{'db_file':results[0][0], "SPESIFIC_HEAT":heat}]

    return {"Timedata":get_specific_event_data(event_filter=event),"event_data":[title_combo, event_mode]}

@api_bp.route('/api/get_specific_event_data', methods=['GET'])
def get_specific_event_data_view():

    from app.models import Session_Race_Records, ActiveEvents
    import random
    from app import db
    from app.lib.db_operation import get_active_event
    
    #Event filter
    event_filter = request.args.get('event_filter', default='', type=str)
    #Spesific heat
    heat_insert = request.args.get('heat', default='', type=str)

    session['index'] = session.get('index', 0) + 1
    
    if event_filter == "":
        active_event = get_active_event()
        try:
            event_filter = db.session.query(ActiveEvents.event_name).filter(ActiveEvents.event_file == active_event[0]["db_file"]).first()[0]
        except:
            print("No active event")
        
    


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
    #Not sure why i added this filter
    #).filter(
    #    Session_Race_Records.finishtime != 0
    ).group_by(
        Session_Race_Records.title_1, Session_Race_Records.title_2
    ).having(
        Session_Race_Records.heat == func.max(Session_Race_Records.heat)
    )

    # Execute the query to get the results
    results = query.all()
    max_len = len(results)
    
    if max_len == 0:
        return "None"
    
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

    event = [{'db_file':results[0][0], "SPESIFIC_HEAT":heat}]

    return {"Timedata":get_specific_event_data(event_filter=event),"event_data":[title_combo, event_mode]}

@api_bp.route('/api/get_event_order', methods=['GET'])
def get_event_order():
    from app.models import ActiveEvents
    from app.lib.db_operation import get_active_event
    event_order = ActiveEvents.query.order_by(ActiveEvents.sort_order).all()
    current_active_event = get_active_event()[0]

    data = []
    
    for a in event_order:

        if str(a.event_file) == str(current_active_event["db_file"]) and str(current_active_event["SPESIFIC_HEAT"]) == str(a.run):
            state = True
        else:
            state = False
        data.append({"Order":a.sort_order, "Event":a.event_name, "Enabled":a.enabled, "Heat":a.run, "Active":state})

    
    return data

@api_bp.route('/api/<string:tab_name>', methods=['GET','POST'])
def api(tab_name):
    if tab_name == 'reload_event':
        return reload_event()
    else:
        return "Invalid tab", 404



@api_bp.route('/api/restart', methods=['GET','POST'])
def restart():
    from app.lib.utils import GetEnv, is_screen_session_running, manage_process_screen
    
    print(manage_process_screen("cross_clock_server.py", "restart"))
    return "data"

@api_bp.route('/api/stop', methods=['GET','POST'])
def stop():
    from app.lib.utils import GetEnv, is_screen_session_running, manage_process_screen
    print(manage_process_screen("cross_clock_server.py", "stop"))
    return "data"

@api_bp.route('/api/start', methods=['GET','POST'])
def start():
    from app.lib.utils import GetEnv, is_screen_session_running, manage_process_screen
    print(manage_process_screen("cross_clock_server.py", "start"))
    return "data"
    
def reload_event():
    data = request.json
    reload_event_func(data["file"], data["run"])
    return data

@api_bp.route('/api/get_timedata/', methods=['GET'])
def get_timedata():
    from app.models import Session_Race_Records
    from flask import request
    from sqlalchemy import desc

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
    from app.models import Session_Race_Records
    from app import db
    import json



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
            "finishtime": record.finishtime / 1_000,
            "snowmobile": record.snowmobile,
            "penalty": record.penalty,
            "points": record.points
        } for record in records
    ]

    return results

@api_bp.route('/api/driver-points', methods=['GET'])
def get_driver_points():
    from app.models import Session_Race_Records
    from app import db
    from sqlalchemy import func

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

    query = query.group_by(Session_Race_Records.first_name, Session_Race_Records.last_name)
    query = query.order_by(func.sum(Session_Race_Records.points).desc(), func.min(Session_Race_Records.finishtime).asc())

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

@api_bp.route('/api/get_start_position_cross', methods=['POST'])
def get_start_position_cross():
    from app.lib.utils import reorder_list_based_on_dict
    from sqlalchemy import desc
    import random
    from app.models import Session_Race_Records, ActiveEvents
    from app import db
    from sqlalchemy import func
    from app.lib.db_operation import get_active_event

    # Extract the list of driver names from the request
    data = request.json
    driver_names = data.get('driverIds', [])  # Adjust this key as necessary
    event = data.get('event')
    event_filter = event.split("-")[0] + "- Kvalifisering"

    # Prepare a query to get the records
    drivers_points = []
    for name in driver_names:
        first_name, last_name = name.split('+')
        driver_record = Session_Race_Records.query.filter(Session_Race_Records.first_name == first_name, Session_Race_Records.last_name == last_name ,Session_Race_Records.title_2.ilike(f"%{event_filter}%")).order_by(Session_Race_Records.points).all()
        points = 0
        for a in driver_record:
            points += int(a.points)

        if driver_record:
            drivers_points.append([first_name+"+"+last_name, points])
        

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
    
    # Assuming dub_dckt and new_order_dups are defined elsewhere in your code
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

    return (combined_list)

@api_bp.route('/api/submit_timestamp_clock', methods=['POST'])
def submit_timestamp_clock():
    import re
    from flask import current_app
    from app.lib.db_operation import get_active_event
    from app.models import ActiveEvents
    from app import db
    from app.lib.utils import get_active_driver_name

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


    #active_driver_id = request.json["driverId"]

    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        active_driver = cur.execute(query).fetchall()
    
    if match:
        device, id, timestamp = match.groups()
        print(f"Device: {device}, ID: {id}, Timestamp: {timestamp}")
    else:
        print("No match found.")

    current_timestamps = current_app.config['timestamp_tracket']

    

    if g_config["dual_start_manual_clock"] == True:
        start_both = True
    else:
        start_both = False

    if len(current_timestamps) > 25:
        current_timestamps.pop(0)
        if button == 1 and start_both == True:
            current_timestamps.pop(0)

    print(print(db_location+active_event_file[0]["db_file"]+".sqlite",active_driver[0][0]))

    if active_event.mode == 0:
        if button == 1:
            current_timestamps.append({"id": len(current_timestamps) + 1, "TITLE": event_title, "HEAT":heat, "DRIVER": active_driver[0][0], "DRIVER_NAME":get_active_driver_name(db_location+active_event_file[0]["db_file"]+".sqlite",active_driver[0][0]), "BUTTON":button,"TS_SIMPLE":timestamp, "TS_RAW":timestamp_raw,"PLACEMENT":"START"})
        if button == 3:
            current_timestamps.append({"id": len(current_timestamps) + 1, "TITLE": event_title, "HEAT":heat, "DRIVER": active_driver[0][0], "DRIVER_NAME":get_active_driver_name(db_location+active_event_file[0]["db_file"]+".sqlite",active_driver[0][0]), "BUTTON":button,"TS_SIMPLE":timestamp, "TS_RAW":timestamp_raw,"PLACEMENT":"FINISH"})
    else:
        if button == 1 and start_both == False:
            current_timestamps.append({"id": len(current_timestamps) + 1, "TITLE": event_title, "HEAT":heat, "DRIVER": active_driver[0][0], "DRIVER_NAME":get_active_driver_name(db_location+active_event_file[0]["db_file"]+".sqlite",active_driver[0][0]), "BUTTON":button,"TS_SIMPLE":timestamp, "TS_RAW":timestamp_raw,"PLACEMENT":"START"})
        elif button == 1 and start_both == True:
            current_timestamps.append({"id": len(current_timestamps) + 1, "TITLE": event_title, "HEAT":heat, "DRIVER": active_driver[0][0], "DRIVER_NAME":get_active_driver_name(db_location+active_event_file[0]["db_file"]+".sqlite",active_driver[0][0]), "BUTTON":button,"TS_SIMPLE":timestamp, "TS_RAW":timestamp_raw,"PLACEMENT":"START"})
            current_timestamps.append({"id": len(current_timestamps) + 1, "TITLE": event_title, "HEAT":heat, "DRIVER": active_driver[0][1], "DRIVER_NAME":get_active_driver_name(db_location+active_event_file[0]["db_file"]+".sqlite",active_driver[0][1]), "BUTTON":button,"TS_SIMPLE":timestamp, "TS_RAW":timestamp_raw,"PLACEMENT":"START"})
        elif button == 2 and start_both == False:
            current_timestamps.append({"id": len(current_timestamps) + 1, "TITLE": event_title, "HEAT":heat, "DRIVER": active_driver[0][1], "DRIVER_NAME":get_active_driver_name(db_location+active_event_file[0]["db_file"]+".sqlite",active_driver[0][1]), "BUTTON":button,"TS_SIMPLE":timestamp, "TS_RAW":timestamp_raw,"PLACEMENT":"START"})
        elif button == 3:
            current_timestamps.append({"id": len(current_timestamps) + 1, "TITLE": event_title, "HEAT":heat, "DRIVER": active_driver[0][0], "DRIVER_NAME":get_active_driver_name(db_location+active_event_file[0]["db_file"]+".sqlite",active_driver[0][0]), "BUTTON":button,"TS_SIMPLE":timestamp, "TS_RAW":timestamp_raw,"PLACEMENT":"FINISH"})
        elif button == 4:
            current_timestamps.append({"id": len(current_timestamps) + 1, "TITLE": event_title, "HEAT":heat, "DRIVER": active_driver[0][1],"DRIVER_NAME":get_active_driver_name(db_location+active_event_file[0]["db_file"]+".sqlite",active_driver[0][1]), "BUTTON":button,"TS_SIMPLE":timestamp, "TS_RAW":timestamp_raw,"PLACEMENT":"FINISH"})
    


    if g_config["auto_commit_manual_clock"] == True:
        send_fixed_timestamp(timestamp_raw)

    #Push changed to the correct websocket
    socketio.emit('response', current_timestamps, room="clock_mgnt")

    return "Success"
    
@api_bp.route('/api/submit_timestamp_clock', methods=['POST'])
def send_fixed_timestamp(timestamp):
    import requests
    from app.models import MicroServices
    from app import db
    import json

    
    clock_server_endpoint = db.session.query(MicroServices.params).filter(
    MicroServices.path == "clock_server_vola.py"
    ).first()[0]

    url = 'http://{0}:5000/send-timestamp'.format(clock_server_endpoint)
    headers = {'Content-Type': 'application/json'}
    response = requests.post(url, headers=headers, data=json.dumps({"timestamp":timestamp}))

    if response.status_code == 200:
        return 'Success'
    else:
        return 'Error'

@api_bp.route('/api/retry_entries', methods=['POST', 'GET'])
def retry_entries():
    import requests
    from app.models import MicroServices, RetryEntries, ActiveEvents, Session_Race_Records
    from app import db
    import json
    from app.lib.db_operation import get_active_event
    from app.lib.utils import get_active_driver_name

    active_event_file = get_active_event()

    active_entry = db.session.query(ActiveEvents.event_name, ActiveEvents.run, ActiveEvents.mode).filter(
    ActiveEvents.event_file == active_event_file[0]["db_file"]
    ).first()

    active_title_heat = active_entry[0]+str(active_entry[1])

    if request.method == 'POST':
        if request.json["method"] == "remove":
            cid = request.json["cid"]
            retry_entries = db.session.query(RetryEntries).filter(RetryEntries.cid == cid).delete()
            db.session.commit()
        else:
            cid = request.json["cid"]
            g_config = GetEnv()
            db_location = g_config["db_location"]
            event_file = db_location + active_event_file[0]["db_file"]+".sqlite"
            
            new_retry_entry = RetryEntries(cid=cid, title=active_title_heat, driver_name=get_active_driver_name(event_file, cid))
            db.session.add(new_retry_entry)
            db.session.commit()
            

    retry_entries = db.session.query(RetryEntries).filter(RetryEntries.title == active_title_heat).all()
    retry_entries_list = []
    for a in retry_entries:
        retry_entries_list.append({
            "CID":a.cid,
            "title":a.title,
            "driver_name":a.driver_name
        })

    socketio.emit('response', json.dumps(retry_entries_list), room="socket_retry")
    return retry_entries_list

@api_bp.route('/api/toggle_retry', methods=['GET'])
def toggle_retry():
    import json
    import requests
    
    driver = request.args.get('driver', default=None, type=str)
    operation = request.args.get('operation', default=None, type=str)

    g_config = GetEnv()

    db_location = g_config["db_location"]
    
    DB_PATH = "site.db"

    if str(driver) == "1":
        query = "SELECT D1 FROM active_drivers;"
    else:
        query = "SELECT D2 FROM active_drivers;"

    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        active_driver = cur.execute(query).fetchall()

    print(active_driver[0][0])

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

    headers = {
    'Content-Type': 'application/json'
    }

    response = requests.request("POST", url, headers=headers, data=payload)
    return "Changed state"


@api_bp.route('/api/set_active_state', methods=['POST'])
def set_active_state():
    from app.models import ActiveDrivers, ActiveEvents
    from app import db
    

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
    send_data_to_room(get_active_startlist())
    return "asd"
    #hostname = data.get('Hostname')

@api_bp.route('/api/ready_state', methods=['GET', 'POST'])
def ready_state():
    from app.lib.utils import Set_active_driver

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
    current_event_file = db_location+"Event"+event.zfill(3)+".sqlite"

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
                
                return str(4)
            if int(a[0]) == int(D1):

                if str(a[1]) != str(0):
                    push = True

        return str(1)

    else:
        for a in driver_data:
            if int(a[0]) == int(D1):
                if a[1] != 0:
                    return str(1)
                else:
                    return str(4)
        return str(4)

@api_bp.route('/api/export/get_new_drivers', methods=['GET'])
def get_new_drivers():
    from app.models import ActiveDrivers, ActiveEvents, archive_server
    from app import db
    import requests
    import json

    archive_params = archive_server.query.first()

    current_drivers = requests.get("http://{0}/get_drivers".format(archive_params.hostname))

    current_drivers = json.loads(current_drivers.text)
    current_events = export_events()

    events_names = []
    new_drivers = []

    for event in current_events:
        for run in event:
            for heat in run:
                if heat == "drivers":
                    try:
                        name = ({"first_name":run[heat][0]["first_name"], "last_name":run[heat][0]["last_name"]})
                        if name not in events_names:
                            events_names.append(name)
                    except:
                        print("Could not add driver")
    
    for a in events_names:
        if (a["first_name"] + " " + a["last_name"]) not in current_drivers:

            new_drivers.append({"name":a, "new":True})
        else:
            new_drivers.append({"name":a, "new":False})

    return {"new_driver":new_drivers, "data":current_events}

@api_bp.route('/api/export/archive_race', methods=['POST'])
def archive_race():
    import json
    import requests
    from app.models import archive_server


    archive_params = archive_server.query.first()

    race_data = request.json

    updated_data = json.dumps(race_data)

    if archive_params.use_use_token:
        headers = {
            'Content-Type': 'application/json',
            'token': '{0}'.format(str(archive_params.auth_token))
        }
    else:
        headers = {
            'Content-Type': 'application/json',
        }

    url = 'http://{0}/upload-data/'.format(archive_params.hostname)


    response = requests.post(url, headers=headers, data=updated_data)
    #response.raise_for_status() 

    data = response.json()
    

    return response.json(), response.status_code


@api_bp.route('/api/export/archive_test', methods=['GET'])
def archive_race_test():
    import json
    import requests
    from app.models import archive_server

    return updated_data

@api_bp.route('/api/set_active_driver_to_next', methods=['GET'])
def set_active_driver_to_next():
    import json
    from app.lib.utils import Set_active_driver
    import requests

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
                    send_data_to_room(event_data)
                    requests.get("http://127.0.0.1:7777/api/active_event_update")
                    return "Driver set"
                if a["drivers"][0]["active"] == True:
                    if int(a["drivers"][0]["time_info"]["FINISHTIME"]) != 0 or int(a["drivers"][0]["time_info"]["PENELTY"]) != 0:
                        active = True

    return "event_name"

@api_bp.route('/api/get_kavli_crit', methods=['GET'])

def get_kavli_crit():
    from app.models import EventKvaliRate
    from app import db

    kvali_criteria = [event.to_dict() for event in EventKvaliRate.query.all()]
    return kvali_criteria