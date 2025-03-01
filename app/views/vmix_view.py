
from flask import Blueprint, render_template, request, session
import sqlite3
from app.lib.db_operation import reload_event as reload_event_func
from app.lib.db_operation import get_active_event, get_active_event_name
from app.models import Session_Race_Records, ActiveEvents, ActiveDrivers
from app import db
import json
from sqlalchemy import func, and_



vmix_bp = Blueprint('vmix', __name__)


@vmix_bp.route('/vmix/startlist_cross_felles', methods=['GET'])
def startlist_cross_felles():
    
    return render_template('vmix/startlist_cross_felles.html')


@vmix_bp.route('/vmix/startlist_cross_felles_rookie', methods=['GET'])
def startlist_cross_felles_rookie():
    
    return render_template('vmix/startlist_cross_felles_rookie.html')

@vmix_bp.route('/vmix/drivers_stats_cross_finale_rookie', methods=['GET'])
def drivers_stats_cross_finale_rookie():
    
    return render_template('vmix/drivers_stats_cross_finale_rookie.html')



@vmix_bp.route('/vmix/drivers_stats_cross_finale', methods=['GET'])
def drivers_stats_cross_finale():
    
    return render_template('vmix/drivers_stats_cross_finale.html')


@vmix_bp.route('/vmix/startlist_cross_single', methods=['GET'])
def startlist_cross_single():
    return render_template('vmix/startlist_cross_single.html')

@vmix_bp.route('/vmix/active_driver_dash_cross', methods=['GET'])
def active_driver_dash_cross():
    
    return render_template('vmix/active_driver_dash_cross.html')

@vmix_bp.route('/vmix/active_driver_stats', methods=['GET'])
def active_driver_stats():
    from flask import current_app
    list_address = current_app.config['listen_address']

    return render_template('vmix/active_driver_dash.html', ip=list_address)

@vmix_bp.route('/vmix/active_driver_stats_single', methods=['GET'])
def active_driver_stats_single():
    
    return render_template('vmix/active_driver_dash_single.html')

@vmix_bp.route('/vmix/active_event_json', methods=['GET'])
def active_event_json():
    event_data = get_active_event_name()
    return "{0}, Heat: {1}".format(event_data["title_2"], event_data["heat"])

@vmix_bp.route('/vmix/top_drivers', methods=['GET'])
def top_drivers():
    results = []
    event = get_active_event_name()
    records = Session_Race_Records.query.filter(Session_Race_Records.finishtime > 0, 
                                                Session_Race_Records.penalty == 0,\
                                                Session_Race_Records.title_2 == event["title_2"]) \
                                        .order_by(Session_Race_Records.finishtime.asc())\
                                        .limit(10)\
                                        .all()

    for t in records:
        results.append([t.first_name + " " + t.last_name, t.finishtime])
    
    return render_template('vmix/top_drivers.html', results=results)

@vmix_bp.route('/vmix/results_event_p_loop', methods=['GET'])
def results_event_p_loop():
    from sqlalchemy import case
    session['index'] = session.get('index', 0) + 1


    results = []

    results_orgin = db.session.query(
        Session_Race_Records.title_1,
        Session_Race_Records.title_2,
        func.max(Session_Race_Records.heat).label('max_heat')
    ).filter(
        and_(
            Session_Race_Records.finishtime != 0,
            Session_Race_Records.penalty == 0
        )
    ).group_by(
        Session_Race_Records.title_1,
        Session_Race_Records.title_2
    ).all()

    events = []

    for a in results_orgin:
        if "Finale" in a[1] or "Stige" in a[1]:
            events.append(a)
    

    if len(events) == 0:
        events = results_orgin
    
    event_count = len(events)

    if event_count < session['index']:
        session['index'] = 1

    event_entry = events.pop(session['index'] - 1)
    
    title = event_entry[1] + " " + "Heat: " + str(event_entry[2])
    #('Eikerapen Bakkeløp', 'Trail Unlimited - Finale', 1)

    records_new = Session_Race_Records.query.filter(
        Session_Race_Records.finishtime > 0,
        Session_Race_Records.title_2 == event_entry[1],
        Session_Race_Records.heat == event_entry[2]
    ).order_by(
        # Adjusted case statement to comply with SQLAlchemy's current API
        case((Session_Race_Records.penalty != 0, 1), else_=0),
        Session_Race_Records.finishtime.asc()
    ).all()

    count = len(records_new)
    results = []
    results2 = []
    entry_count = 0
    for t in records_new:
        entry_count += 1
        results.append([str(entry_count),t.first_name + " " + t.last_name, t.finishtime, t.penalty, t.snowmobile])

    if count > 15:
        count_data = count//2
        results2 = results[count_data:]
        results = results[:count_data]

    return render_template('vmix/results_event_top_loop.html', results=results, results2=results2, title=title)


@vmix_bp.route('/vmix/results_event', methods=['GET'])
def results_event():
    from sqlalchemy import case

    results = []
    results2 = []

    event = get_active_event_name()
    heat = event["heat"].split("/")[0]
    title = event["title_2"] + " " + "Heat: " + event["heat"]
    records = Session_Race_Records.query.filter(
        Session_Race_Records.finishtime > 0,
        Session_Race_Records.title_2 == event["title_2"],
        Session_Race_Records.heat == heat
    ).order_by(
        # Adjusted case statement to comply with SQLAlchemy's current API
        case((Session_Race_Records.penalty != 0, 1), else_=0),
        Session_Race_Records.finishtime.asc()
    ).all()
    count = len(records)


    entry_count = 0
    for t in records:
        entry_count += 1
        results.append([str(entry_count),t.first_name + " " + t.last_name, t.finishtime, t.penalty, t.snowmobile])

    if count > 20:
        count_data = count//2
        results2 = results[count_data:]
        results = results[:count_data]
    
    return render_template('vmix/results_event.html', results=results, results2=results2, title=title)

@vmix_bp.route('/vmix/drivers_stats_cross', methods=['GET'])
def drivers_stats_cross():
    from app.models import Session_Race_Records
    from app import db
    import json
    from sqlalchemy import func, and_, or_

    loop = request.args.get('loop')
    heat = request.args.get('heat')
    active = request.args.get('active')
    all_event = request.args.get('all')
    all_heats = request.args.get('all_heats')
    event_filter = request.args.get('event_filter')
    finale = request.args.get('finale')

    query = Session_Race_Records.query
    query = query.order_by(Session_Race_Records.points.desc(), Session_Race_Records.finishtime.asc())
    
    if finale:
        query = query.filter(Session_Race_Records.title_2.ilike("%FINALE%"))
        title = "FINALE"
    elif all_event:
        title = get_active_event_name()["title_1"]
    elif active == "true":
        data = get_active_event_name()
        title_2 = data["title_2"]
        query = query.filter(Session_Race_Records.title_2.ilike(f"%{title_2}%"))
    
        if heat == "true":
            heat_new = get_active_event()[0]["SPESIFIC_HEAT"]
            query = query.filter(Session_Race_Records.heat == heat_new)
            title = title_2 + " " + data["heat"]
        else:
            title = title_2
    
    if loop:
        session['index'] = session.get('index', 0) + 1
        if event_filter:
            results_orgin = db.session.query(
                Session_Race_Records.title_1,
                Session_Race_Records.title_2,
                func.max(Session_Race_Records.heat).label('max_heat')
            ).filter(
                and_(
                    or_(
                        and_(Session_Race_Records.finishtime != 0, Session_Race_Records.penalty == 0),
                        Session_Race_Records.penalty > 0
                    ),
                    Session_Race_Records.title_2 == event_filter,
                )
            )
        elif all_heats:
            results_orgin = db.session.query(
                Session_Race_Records.title_1,
                Session_Race_Records.title_2,
                func.max(Session_Race_Records.heat).label('max_heat')
            ).filter(
                or_(
                    and_(Session_Race_Records.finishtime != 0, Session_Race_Records.penalty == 0),
                    Session_Race_Records.penalty > 0
                )
            )
        else:
            results_orgin = db.session.query(
                Session_Race_Records.title_1,
                Session_Race_Records.title_2,
                func.max(Session_Race_Records.heat).label('max_heat')
            ).filter(
                or_(
                    and_(Session_Race_Records.finishtime != 0, Session_Race_Records.penalty == 0),
                    Session_Race_Records.penalty > 0
                )
            )
        
        if finale:
            results_orgin = results_orgin.filter(Session_Race_Records.title_2.ilike("%FINALE%"))
        
        results_orgin = results_orgin.group_by(
            Session_Race_Records.title_1,
            Session_Race_Records.title_2,
        ).all()
        
        event_count = len(results_orgin)
        if event_count < session['index']:
                session['index'] = 1

        event_entry = results_orgin[session['index'] - 1]

        if heat:
            title = event_entry[1] + " " + "Heat: " + str(event_entry[2])
        else:
            title = event_entry[1]

        query = query.filter(Session_Race_Records.title_2.ilike(f"%{event_entry[1]}%"))
        
        if heat:
            query = query.filter(Session_Race_Records.heat == event_entry[2])

    records = query.all()

    results = [
        {
            "id": record.id,
            "first_name": record.first_name,
            "last_name": record.last_name,
            "title_1": record.title_1,
            "title_2": record.title_2,
            "heat": record.heat,
            "finishtime": record.finishtime / 1_000 if record.finishtime != 0 else 0,
            "snowmobile": record.snowmobile,
            "penalty": record.penalty,
            "points": record.points
        } for record in records
    ]

    combined_results = {}

    for record in results:
        name_key = f"{record['first_name']} {record['last_name']}"
        
        if name_key not in combined_results:
            combined_results[name_key] = {
                "first_name": record['first_name'],
                "last_name": record['last_name'],
                "snowmobile": record['snowmobile'],
                "points": record['points'],
                "finishtime": record['finishtime'] if record['finishtime'] != 0 else float('inf'),
                "penalty": record['penalty']
            }
        else:
            combined_results[name_key]['points'] += record['points']
            if record['finishtime'] != 0 and record['finishtime'] < combined_results[name_key]['finishtime']:
                combined_results[name_key]['finishtime'] = record['finishtime']
            if record['penalty'] > combined_results[name_key]['penalty']:
                combined_results[name_key]['penalty'] = record['penalty']

    for key, value in combined_results.items():
        if value['finishtime'] == float('inf'):
            value['finishtime'] = 0

    # New sorting function
    def sort_key(entry):
        points = entry['points']
        finishtime = entry['finishtime']
        return (-points, finishtime if finishtime != 0 else float('inf'))

    sorted_combined_results = sorted(combined_results.values(), key=sort_key)

    sorted_combined_results_new = []
    counter = 1
    for a in sorted_combined_results:
        a["number"] = counter
        sorted_combined_results_new.append(a)
        counter += 1

    count = len(sorted_combined_results_new)
    if count > 20:
        count_data = count//2
        combined_results3 = sorted_combined_results_new[count_data:]
        combined_results2 = sorted_combined_results_new[:count_data]
    else:
        combined_results3 = []
        combined_results2 = sorted_combined_results_new

    return render_template('vmix/drivers_stats_cross.html', results=combined_results2, results2=combined_results3, title=title)

@vmix_bp.route('/vmix/get_startlist', methods=['GET'])
def get_startlist():
    from app.lib.utils import GetEnv
    db_location = GetEnv()["db_location"]
    event = get_active_event()
    heat = event[0]["SPESIFIC_HEAT"]

    driver_entries = []

    event_name = get_active_event_name()
    event = get_active_event()

    with sqlite3.connect(db_location + event[0]["db_file"]+".sqlite") as conn:
        cursor = conn.cursor()
        mode = cursor.execute("SELECT MODE FROM db_index;".format(heat)).fetchall()
        startlist_cid = cursor.execute("SELECT * FROM startlist_r{0};".format(heat)).fetchall()
        drivers = cursor.execute("SELECT * FROM drivers").fetchall()

    
    count = 0
    driver1 = ""
    driver2 = ""

    if int(mode[0][0]) == int(0):
        for b in startlist_cid:
            for m in drivers:
                if int(startlist_cid[count][1]) == int(m[0]):
                    driver1 = m

            driver_entries.append((driver1))
            count = count + 1 
        title = event_name["title_2"] + " " + event_name["heat"]
        return render_template('vmix/startlist_s.html', results=driver_entries, title=title)

    else:
        for b in range(0,int(len(startlist_cid)/2)):
            for m in drivers:
                if int(startlist_cid[count][1]) == int(m[0]):
                    driver1 = m
            for m in drivers:
                if int(startlist_cid[count+1][1]) == int(m[0]):
                    driver2 = m
            driver_entries.append((driver1,driver2))
            count = count+2 
        title = event_name["title_2"] + " " + event_name["heat"]
        return render_template('vmix/startlist_p.html', results=driver_entries, title=title)
    

    

@vmix_bp.route('/vmix/get_startlist_loop', methods=['GET'])
def get_startlist_loop():
    from app.lib.utils import GetEnv
    from app.models import ActiveDrivers


    session['index'] = session.get('index', 0) + 1
    db_location = GetEnv()["db_location"]
    driver_entries = []

    # Retrieve query parameters
    event_type = request.args.get('event_type')
    heat = request.args.get('heat')
    event_name = request.args.get('event_name')
    all_event = request.args.get('all', type=bool)
    display_current_heat = request.args.get('current_heat')
    from_active_event = request.args.get('from_active_event', type=bool)
 
    


    query = db.session.query(ActiveEvents.event_file, ActiveEvents.run, ActiveEvents.mode, ActiveEvents.sort_order, ActiveEvents.event_name).filter(ActiveEvents.enabled == True)

    if from_active_event:
        active_event = get_active_event()
        active_event_file = active_event[0]["db_file"]
        active_event_run = active_event[0]["SPESIFIC_HEAT"]
        current_id = db.session.query(ActiveEvents.sort_order).filter(ActiveEvents.run == int(active_event_run), ActiveEvents.event_file == active_event_file).first()[0]
        query = query.filter(ActiveEvents.sort_order > current_id)

    if heat:
        query = query.filter(ActiveEvents.run == heat)
    else:
        event = get_active_event()
        heat = event[0]["SPESIFIC_HEAT"]
        
    if event_type:
        query = query.filter(ActiveEvents.event_name.like(f"%{event_type}%"))  # Use %like% for partial matches
    if event_name:
        query = query.filter(ActiveEvents.event_name.like(f"%{event_name}%"))  # Use %like% for partial matches

    query = query.order_by(ActiveEvents.sort_order.asc())
    active_events = query.all()

    event_count = len(active_events)
    
    if event_count < session['index']:
        session['index'] = 1

    event = active_events.pop(session['index'] - 1)

    db_file = event[0]
    heat = event[1]
    

    with sqlite3.connect(db_location + db_file +".sqlite") as conn:
        cursor = conn.cursor()
        mode = cursor.execute("SELECT MODE FROM db_index;".format(heat)).fetchall()
        startlist_cid = cursor.execute("SELECT * FROM startlist_r{0};".format(heat)).fetchall()
        drivers = cursor.execute("SELECT * FROM drivers").fetchall()

    count = 0
    driver1 = ""
    driver2 = ""

    if int(mode[0][0]) == int(0):
        for b in startlist_cid:
            for m in drivers:
                if int(startlist_cid[count][1]) == int(m[0]):
                    driver1 = m

            driver_entries.append((driver1))
            count = count + 1 
        title = event.event_name + " Heat: " + str(heat)
        return render_template('vmix/startlist_s_loop.html', results=driver_entries, title=title)
    else:
        for b in range(0,int(len(startlist_cid)/2)):
            for m in drivers:
                if int(startlist_cid[count][1]) == int(m[0]):
                    driver1 = m
            for m in drivers:
                if int(startlist_cid[count+1][1]) == int(m[0]):
                    driver2 = m
            driver_entries.append((driver1,driver2))
            count = count+2 
            title = event.event_name + " Heat: " + str(heat)
        return render_template('vmix/startlist_p_loop.html', results=driver_entries, title=title)
    #return "{0}{1}".format(session['index'],event_count)
    

@vmix_bp.route('/vmix/get_active_driver_single', methods=['GET'])
def get_active_driver_single():
    from app.lib.utils import GetEnv
    
    query = db.session.query(ActiveDrivers.D1)
    active_driver = query.first()[0]
    event = get_active_event()
    db_file = event[0]["db_file"]
    heat = event[0]["SPESIFIC_HEAT"]
    db_location = GetEnv()["db_location"]

    with sqlite3.connect(db_location + db_file +".sqlite") as conn:
        cursor = conn.cursor()
        drivers = cursor.execute("SELECT * FROM drivers").fetchall()
        driver_stats = cursor.execute("SELECT CID, FINISHTIME FROM driver_stats_r{0};".format(heat)).fetchall()


    for t in drivers:
        if int(active_driver) == int(t[0]):
            driver_name = t[1] + " " + t[2]
            snowmobile = t[4]
            for g in driver_stats:
                if int(g[0]) == int(active_driver):
                    finishtime = g[1]
        

    driver_data = {"NAME":driver_name, "SNOWMOBILE":snowmobile, "FINISHTIME":finishtime/1000}
    
    return driver_data

@vmix_bp.route('/vmix/get_event_order_vmix', methods=['GET'])
def get_event_order_vmix():
    from app.models import ActiveEvents
    from app.lib.db_operation import get_active_event
    event_order = ActiveEvents.query.order_by(ActiveEvents.sort_order).filter(ActiveEvents.enabled == True).all()
    current_active_event = get_active_event()[0]

    data = []
    for a in event_order:

        if str(a.event_file) == str(current_active_event["db_file"]) and str(current_active_event["SPESIFIC_HEAT"]) == str(a.run):
            state = True
        else:
            state = False
        if state == 1:
            state = True
        else:
            state = False
        data.append({"Order":a.sort_order, "Event":a.event_name, "Enabled":a.enabled, "Heat":a.run, "active":state})

    count = len(data)

    if count > 20:
        count_data = count // 2
        if count % 2 != 0:
            count_data += 1

        results = data[:count_data]
        results2 = data[count_data:]
    else:
        results = data
        results2 = []

    return render_template('vmix/get_event_order_vmix.html', events=results, events2=results2)

@vmix_bp.route('/vmix/get_active_ladder', methods=['GET'])
def get_active_ladder():
    return render_template('vmix/active_ladder.html')