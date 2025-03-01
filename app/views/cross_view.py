from flask import Blueprint, request, send_from_directory, session, render_template
import sqlite3
from app.lib.db_operation import reload_event as reload_event_func
from app.lib.db_operation import update_active_event_stats, get_active_startlist, get_active_startlist_w_timedate, get_specific_event_data
from app import socketio
from app.lib.utils import intel_sort, update_info_screen, export_events, GetEnv
from sqlalchemy import func
from app.lib.utils import convert_microseconds_to_time
import requests



cross_bp = Blueprint('cross', __name__)


@cross_bp.route('/cross/submit_timestamp', methods=['POST'])
def submit_cross_timestamp():
    
    timestamp = str(request.form.get("timestamp"))
    id = str(request.form.get("id"))
    base_time = str(request.form.get("basetime"))

    if int(timestamp) > int(base_time):
        basetime_stamp_final = (int(timestamp) + int(base_time))
    else:
        basetime_stamp_final = (int(base_time) + int(timestamp))

    time_stamp_new = convert_microseconds_to_time(basetime_stamp_final)
    print(time_stamp_new)

    data = "<BOX {1} {0} 23 01 2 1567>\n".format(time_stamp_new, id.zfill(6))
    data += "\n"
    print(data)

    
    response = requests.post('http://192.168.1.50:2009', data={'message': data})
    #requests.get("http://192.168.1.50:7777/api/active_event_update")

    return {'status': 'success'}

@cross_bp.route('/cross/submit_timestamp_par', methods=['POST'])
def submit_timestamp_par():
    
    timestamp = str(request.form.get("timestamp"))
    id = str(request.form.get("id"))
    base_time = str(request.form.get("basetime"))

    if int(timestamp) > int(base_time):
        basetime_stamp_final = (int(timestamp) + int(base_time))
    else:
        basetime_stamp_final = (int(base_time) + int(timestamp))

    time_stamp_new = convert_microseconds_to_time(basetime_stamp_final)
    print(time_stamp_new)

    data = "<BOX {1} {0} 23 01 2 1567>\n".format(time_stamp_new, id.zfill(6))
    data += "\n"

    
    response = requests.post('http://192.168.1.50:2009', data={'message': data})
    #requests.get("http://192.168.1.50:7777/api/active_event_update")

    return {'status': 'success'}


@cross_bp.route('/cross/submit_timestamp_old', methods=['POST'])
def submit_cross_timestamp_old():
    timestamp = str(request.form.get("timestamp"))
    id = str(request.form.get("id"))
    start_list_dict, con_title, eventex = get_event_data()

    for a in start_list_dict:
        if start_list_dict[a][0] == int(id):
            basetime_stamp = start_list_dict[a][5][3]

    print(timestamp, basetime_stamp)
    if int(timestamp) > basetime_stamp:
        basetime_stamp_final = (int(timestamp) + (basetime_stamp))
    else:
        basetime_stamp_final = ((basetime_stamp) + int(timestamp))
    print(basetime_stamp_final)
   
    print(convert_microseconds_to_time((basetime_stamp - 1) - int(timestamp)))
    time_stamp_new = convert_microseconds_to_time(basetime_stamp_final)
    print(time_stamp_new)

    data = "<BOX {1} {0} 23 01 2 1567>\n".format(time_stamp_new, id.zfill(6))
    data += "\n"
    response = requests.post('http://192.168.1.50:2009', data={'message': data})
    #start_list_dict, con_title, eventex = get_event_data()
    #time.sleep(1)
    return {'status': 'success'}


@cross_bp.route('/cross/clock', methods=['GET'])
def clock():
    drivers = {"1": [8, "Aleksander", "Hobbesland", "\u00c5seral Sn\u00f8scooterklubb", "Skidoo", [0, 2, 0, 43338420000], "Started"], "2": [3, "Erlend", "N\u00f8kland", "\u00c5seral Sn\u00f8scooterklubb", "Polaris 850", [0, 3, 0, 44375524000], "Started"], "3": [17, "Jakob", "Austegard", "\u00c5seral Sn\u00f8scooterklubb", "ski doo 800", [0, 2, 0, 43966950000], "Started"], "4": [10, "Emil", "Vatne", "\u00c5seral Sn\u00f8scooterklubb", "Lynx rs", [0, 1, 0, 44180900000], "Started"], "5": [747, "Helge", "Oland", "\u00c5mli Og Nissedal Motorklubb", "Ski-doo Tundra", [130510, 0, 0, 44494110000], "Done"], "6": [2, "J\u00f8rund Haugland", "\u00c5sland", "\u00c5seral Sn\u00f8scooterklubb", "Polaris 800", [129495, 0, 0, 44646407000], "Done"]}
    return render_template('cross/clock.html', drivers=drivers)

@cross_bp.route('/cross/clock_1', methods=['GET'])
def clock_1():
    drivers = {"1": [8, "Aleksander", "Hobbesland", "\u00c5seral Sn\u00f8scooterklubb", "Skidoo", [0, 2, 0, 43338420000], "Started"], "2": [3, "Erlend", "N\u00f8kland", "\u00c5seral Sn\u00f8scooterklubb", "Polaris 850", [0, 3, 0, 44375524000], "Started"], "3": [17, "Jakob", "Austegard", "\u00c5seral Sn\u00f8scooterklubb", "ski doo 800", [0, 2, 0, 43966950000], "Started"], "4": [10, "Emil", "Vatne", "\u00c5seral Sn\u00f8scooterklubb", "Lynx rs", [0, 1, 0, 44180900000], "Started"], "5": [747, "Helge", "Oland", "\u00c5mli Og Nissedal Motorklubb", "Ski-doo Tundra", [130510, 0, 0, 44494110000], "Done"], "6": [2, "J\u00f8rund Haugland", "\u00c5sland", "\u00c5seral Sn\u00f8scooterklubb", "Polaris 800", [129495, 0, 0, 44646407000], "Done"]}
    return render_template('cross/clock_1.html', drivers=drivers)

        
@cross_bp.route('/cross/clock_par', methods=['GET'])
def clock_par():
    drivers = {"1": [8, "Aleksander", "Hobbesland", "\u00c5seral Sn\u00f8scooterklubb", "Skidoo", [0, 2, 0, 43338420000], "Started"], "2": [3, "Erlend", "N\u00f8kland", "\u00c5seral Sn\u00f8scooterklubb", "Polaris 850", [0, 3, 0, 44375524000], "Started"], "3": [17, "Jakob", "Austegard", "\u00c5seral Sn\u00f8scooterklubb", "ski doo 800", [0, 2, 0, 43966950000], "Started"], "4": [10, "Emil", "Vatne", "\u00c5seral Sn\u00f8scooterklubb", "Lynx rs", [0, 1, 0, 44180900000], "Started"], "5": [747, "Helge", "Oland", "\u00c5mli Og Nissedal Motorklubb", "Ski-doo Tundra", [130510, 0, 0, 44494110000], "Done"], "6": [2, "J\u00f8rund Haugland", "\u00c5sland", "\u00c5seral Sn\u00f8scooterklubb", "Polaris 800", [129495, 0, 0, 44646407000], "Done"]}
    return render_template('cross/clock_par.html', drivers=drivers)
