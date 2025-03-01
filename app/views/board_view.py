from app import socketio
from flask import Blueprint, render_template, request, session
from app.lib.db_operation import reload_event as reload_event_func
from flask_socketio import join_room, send
from app.models import SpeakerPageSettings
from app import db
from sqlalchemy import func


board_bp = Blueprint('board', __name__)

@board_bp.route('/board/startlist_simple')
def startlist_simple():
    return render_template('board/startlist_active_simple.html')

@board_bp.route('/board/startlist_simple_upcoming')
def startlist_simple_upcoming():
    from app.lib.db_operation import get_active_event
    from app.models import ActiveEvents
    from app.lib.utils import GetEnv
    import sqlite3

    db_location = GetEnv()["db_location"]
    event = get_active_event()
    heat = event[0]["SPESIFIC_HEAT"]
    with sqlite3.connect(db_location + event[0]["db_file"]+".sqlite") as conn:
        cursor = conn.cursor()
        mode = cursor.execute("SELECT MODE FROM db_index;".format(heat)).fetchall()

    mode = mode[0][0]
    if int(mode) == 0:
        return render_template('board/startlist_active_upcoming_single.html')
    else:
        return render_template('board/startlist_active_upcoming.html')

@board_bp.route('/board/startlist_simple_loop')
def startlist_simple_loop():

    return render_template('board/startlist_active_simple_loop.html')

@board_bp.route('/board/startlist_simple_loop_single')
def startlist_simple_loop_single():

    return render_template('board/startlist_active_simple_loop_single.html')

@board_bp.route('/board/scoreboard')
def scoreboard():
    return render_template('board/scoreboard.html')

@board_bp.route('/board/scoreboard_c')
def scoreboard_columns():
    return render_template('board/scoreboard_columns.html')

@board_bp.route('/board/ladder/')
def ladders():
    ladder = request.args.get('ladder', default='', type=str)
    if ladder == '':
        return render_template('board/ladder/active_ladder.html')
    else:
        return render_template('board/ladder/teams-{0}.html'.format(ladder))

@board_bp.route('/board/ladder/loop')
def ladders_loop():
    return render_template('board/ladder/ladder_loop.html')

@board_bp.route('/board/scoreboard_loop')
def scoreboard_loop_old():

    from app.models import Session_Race_Records, ActiveEvents
    import random

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
            (Session_Race_Records.title_1 + Session_Race_Records.title_2).like('%Kvalifisering%')
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
    event_int = random.randint(0, max_len-1)
    title_combo = results[event_int][3] + " " + results[event_int][4]

    query = db.session.query(ActiveEvents.event_file).filter(
        ActiveEvents.event_name == title_combo
    )

    results = query.first()
    
    return str(session['index'])

@board_bp.route('/board/speaker/', methods = ['GET', 'POST'])
def speaker():
    from app.lib.db_operation import get_active_event
    from app.models import ActiveEvents, EventKvaliRate
    from app import db
    from app.lib.utils import GetEnv
    import json
    g_config = GetEnv()


    active_event = get_active_event()
    query = db.session.query(ActiveEvents.event_file, ActiveEvents.run, ActiveEvents.mode).filter(
    ActiveEvents.event_file == active_event[0]["db_file"]
    )
    results = query.first()
    mode = results[2]

    SpeakerPageConfig = SpeakerPageSettings.query.first()

    kvali_criteria = [event.to_dict() for event in EventKvaliRate.query.all()]


    if request.method == 'POST':
        data = request.get_json()

        SpeakerPageConfig.match_parrallel = data["matchingParallel"]
        SpeakerPageConfig.h_server_url = data["h_server_url"]

        db.session.commit()
    
    SpeakerPageConfig_json = {"matching_parallel":SpeakerPageConfig.match_parrallel,"h_server_url":SpeakerPageConfig.h_server_url}
    cross_state = g_config["cross"]
    if str(cross_state) == "True":
        return render_template('board/speaker_board_cross.html', SpeakerPageConfig_json=SpeakerPageConfig_json)
    
    elif mode == 1 or mode == 2 or mode == 3:
        return render_template('board/speaker_board_p.html', SpeakerPageConfig_json=SpeakerPageConfig_json, kvali_criteria=json.dumps(kvali_criteria))
    else:
        return render_template('board/speaker_board_s.html', SpeakerPageConfig_json=SpeakerPageConfig_json)
    

    

@board_bp.route('/board/startlist_active_simple_single')
def startlist_active_simple_single():
    return render_template('board/startlist_active_simple_single.html')

@board_bp.route('/board/startlist_active_simple_single_finale')
def startlist_active_simple_single_finale():
    return render_template('board/startlist_active_simple_single_finale.html')
    

@board_bp.route('/board/scoreboard_cross', methods=['GET'])
def scoreboard_cross():
    from app.models import Session_Race_Records
    from app import db
    import json
    from app.lib.db_operation import get_active_event, get_active_event_name
    from sqlalchemy import func, and_



    loop = request.args.get('loop')
    heat = request.args.get('heat')
    active = request.args.get('active')
    all_event = request.args.get('all')
    event = request.args.get('event')
    all_heats = request.args.get('all_heats')


    query = Session_Race_Records.query
    query = query.order_by(Session_Race_Records.points.desc(), Session_Race_Records.finishtime.asc())
    
    if event:
        query = query.filter(Session_Race_Records.title_2.ilike(f"%{event}%"))
        records = query.all()

    if all_event:
        title = get_active_event_name()["title_1"]
        records = query.all()


    if active == "true":
        data = get_active_event_name()
        title_2 = data["title_2"]
        query = query.filter(Session_Race_Records.title_2.ilike(f"%{title_2}%"))
        title = title_2

        if heat == "true":
            heat == data["heat"]
            heat_new = get_active_event()[0]["SPESIFIC_HEAT"]
            query = query.filter(Session_Race_Records.heat == heat_new)
            title = title_2 + " " + data["heat"]
        else:
            title = title_2

        records = query.all()
    
    if loop:
        session['index'] = session.get('index', 0) + 1
        if not all_heats:
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

            event_count = len(results_orgin)
            if event_count < session['index']:
                    session['index'] = 1
        else:
            results_orgin = db.session.query(
                Session_Race_Records.title_1,
                Session_Race_Records.title_2,
            ).filter(
                and_(
                    Session_Race_Records.finishtime != 0,
                    Session_Race_Records.penalty == 0
                )
            ).group_by(
                Session_Race_Records.title_1,
                Session_Race_Records.title_2
            ).all()
            event_count = len(results_orgin)
            print(event_count)

            if event_count < session['index']:
                    session['index'] = 1

        event_entry = results_orgin.pop(session['index'] - 1)

        if heat:
            title = event_entry[1] + " " + "Heat: " + str(event_entry[2])
        else:
            title = event_entry[1]

        query = query.filter(Session_Race_Records.title_2.ilike(f"%{event_entry[1]}%"))
        
        if heat:
            query = query.filter(Session_Race_Records.heat == event_entry[2])

        records = query.all()
    print(records)

    results = [
        {
            "id": record.id,
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

    combined_results = {}

    for record in results:
        name_key = f"{record['first_name']} {record['last_name']}"
        
        if name_key not in combined_results:
            combined_results[name_key] = {
                "first_name": record['first_name'],
                "last_name": record['last_name'],
                "snowmobile": record['snowmobile'],
                "points": record['points'],
                "finishtime": record['finishtime'] if record['finishtime'] != 0 else float('inf')
            }
        else:
            combined_results[name_key]['points'] += record['points']
            if 0 < record['finishtime'] < combined_results[name_key]['finishtime']:
                combined_results[name_key]['finishtime'] = record['finishtime']

    for key, value in combined_results.items():
        if value['finishtime'] == float('inf'):
            value['finishtime'] = 0
    
    sorted_combined_results = sorted(combined_results.values(), key=lambda x: x['points'], reverse=True)


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

    return render_template('board/scoreboard_cross.html', results=combined_results2, results2=combined_results3, title=title)