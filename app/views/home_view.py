
from flask import Blueprint, render_template, request
import sqlite3
from app.lib.db_operation import reload_event as reload_event_func
from app.lib.db_operation import get_active_event
from app.models import ActiveEvents, Session_Race_Records
from app.lib.utils import get_active_events_sorted


home_bp = Blueprint('home', __name__)


@home_bp.route('/home/home', methods=['GET'])
def homepage():
    return render_template('home/index.html')

@home_bp.route('/home/cross_resultat', methods=['GET'])
def home_cross():
    events = get_active_events_sorted()

    grouped_events = {}
    for event in events:
        event_name = event['Event'].rsplit(' - ', 1)[0]
        if event_name not in grouped_events:
            grouped_events[event_name] = []
        grouped_events[event_name].append(event)
        
    print(grouped_events)
    return render_template('home/cross_resultat.html', grouped_events=grouped_events)

@home_bp.route('/home/startlist', methods=['GET'])
def home_startlist():
    return render_template('home/startlist.html')

@home_bp.route('/home/ladder', methods=['GET'])
def home_ladder():
    return render_template('home/ladder.html')

@home_bp.route('/home/results', methods=['GET'])
def home_results():
    return render_template('home/results.html')

@home_bp.route('/home/manual_clock', methods=['GET'])
def manual_clock():
    from app.lib.db_operation import get_active_event
    from app.models import ActiveEvents
    from app import db

    active_event_file = get_active_event()

    active_entry = db.session.query(ActiveEvents.mode).filter(
    ActiveEvents.event_file == active_event_file[0]["db_file"]
    ).first()

    mode = active_entry.mode
    if mode == 3 or mode == 2:
        return render_template('home/par_clock.html')
    else:
        return render_template('home/single_clock.html')
    
