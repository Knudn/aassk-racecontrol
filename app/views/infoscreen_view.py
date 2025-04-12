
from flask import Blueprint, redirect, render_template, request
from app.config.websocket_config import emit_to_room, SOCKET_ROOMS
from app import socketio


infoscreen_bp = Blueprint('infoscreen', __name__)

@infoscreen_bp.route('/infoscreen/infoscreen', methods=['GET'])
def websocket_test():
    return render_template('websocket_test.html')

@infoscreen_bp.route('/infoscreen/set_session', methods=['GET', 'POST'])
def send_to_websocket():
    data = request.get_json()
    sid = data["sid"]
    print(data)
    with open("app/templates/board/startlist_active_simple.html", "r") as f:
        page = f.read()

    emit_to_room(socketio, page, room=sid)
    return "DONE"    