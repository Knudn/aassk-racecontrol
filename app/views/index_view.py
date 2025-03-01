
from flask import Blueprint, render_template
from app import socketio, join_room, emit


index_bp = Blueprint('index', __name__)

@index_bp.route('/')
def index():
    return render_template('home/index.html')


@socketio.on('join')
def on_join(data):
    username = data['username']
    room = data['room']
    join_room(room)
    print(f'{username} has joined {room}')
    # Optionally, notify others in the room
    emit('status', {'msg': f'{username} has joined the room.'}, room=room)
