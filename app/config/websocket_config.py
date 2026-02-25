# app/config/websocket_config.py
from flask_socketio import emit, join_room
from flask import request
import json
from collections import defaultdict
import time
from app import socketio

SOCKET_ROOMS = {
    'default': 'default',
    'clock_management': 'clock_mgnt',
    'retry_notifications': 'socket_retry',
    'infoscreen': 'infoscreen',
    'admin': 'admin',
    'prestage_lights': 'prestage_lights',
    'start_state': 'start_state',
    'overlay': 'overlay',
}

SOCKET_EVENTS = {
    'standard_response': 'response',
        'admin_update': 'admin_update',
    'session_list': 'session_list'
}

active_sessions = defaultdict(list)

def send_data_to_room(msg, room=None):
    """Sends data to a specified socket room"""
    if request.args.get('room'):
        room = request.args.get('room')
    elif room is None:
        room = SOCKET_ROOMS['default']
        
    emit_to_room(socketio, msg, room)
    return {"message": f"Data sent to room: {room}"}


def emit_to_room(socketio, data, room=None):
    """
    Emits data to a specific socket room
    
    Args:
        socketio: Flask-SocketIO instance
        data: Data to emit
        room: Room name (uses default if None)
    """
    if room is None:
        room = SOCKET_ROOMS['default']
    
    if not isinstance(data, str):
        data = json.dumps(data)
    
    socketio.emit(SOCKET_EVENTS['standard_response'], data, room=room)

def emit_to_client(socketio, data, sid):
    """
    Emits data to a specific client by SID
    
    Args:
        socketio: Flask-SocketIO instance
        data: Data to emit
        sid: Client's session ID
    """
    if not isinstance(data, str):
        data = json.dumps(data)
    
    socketio.emit(SOCKET_EVENTS['standard_response'], data, room=sid)

def get_active_sessions(room=None):
    """
    Get all active sessions, optionally filtered by room
    
    Args:
        room: Room to filter by (None for all sessions)
    
    Returns:
        List of session information dictionaries
    """
    if room:
        return active_sessions.get(room, [])
    
    all_sessions = []
    for room_name, sessions in active_sessions.items():
        for session in sessions:
            session_copy = session.copy()
            session_copy['room'] = room_name
            all_sessions.append(session_copy)
    
    return all_sessions

def register_socket_events(socketio):
    """
    Register all socket event handlers
    
    Args:
        socketio: Flask-SocketIO instance
    """
    
    @socketio.on('connect')
    def handle_connect():
        """Handle client connection"""
        print(f"Client connected with SID: {request.sid}")
    
    @socketio.on('disconnect')
    def handle_disconnect():
        """Handle client disconnection"""
        for room in active_sessions:
            active_sessions[room] = [session for session in active_sessions[room] 
                                    if session.get('sid') != request.sid]
        
        socketio.emit(SOCKET_EVENTS['admin_update'], {'action': 'disconnect', 'sid': request.sid}, 
                     room=SOCKET_ROOMS['admin'])
        print(f"Client disconnected with SID: {request.sid}")
    
    @socketio.on('join')
    def on_join(data):
        """Handle client joining a room"""
        username = data.get('username', 'anonymous')
        room = data.get('room', SOCKET_ROOMS['default'])
        hostname = data.get('hostname', 'unknown')
        join_room(room)
        
        session_info = {
            'sid': request.sid,
            'username': username,
            'hostname': hostname,
            'ip': request.remote_addr,
            'user_agent': request.headers.get('User-Agent', 'unknown'),
            'connected_at': time.time(),
            'last_active': time.time()
        }
        
        exists = False
        for i, session in enumerate(active_sessions[room]):
            if session.get('sid') == request.sid:
                active_sessions[room][i] = session_info
                exists = True
                break
        
        if not exists:
            active_sessions[room].append(session_info)
        
        print(f"Client {username} (SID: {request.sid}) joined room: {room}")
        
        emit('joined', {'status': 'success', 'room': room, 'session_id': request.sid})
         
        if room == SOCKET_ROOMS['infoscreen']:
            socketio.emit(SOCKET_EVENTS['admin_update'], 
                         {'action': 'join', 'session': session_info}, 
                         room=SOCKET_ROOMS['admin'])
        if room == "start_state":
            from flask import current_app
            state = current_app.config.get('start_state', {})
            emit(SOCKET_EVENTS['standard_response'], json.dumps(state))
        elif room == "active_dash":
            from app.lib.utils import get_dash_data
            payload = get_dash_data()
            emit(SOCKET_EVENTS["standard_response"], json.dumps(payload))
        elif room == 'results':
            pass
    
    @socketio.on('message')
    def handle_message(data):
        """Handle incoming messages"""
        username = data.get('username', 'anonymous')
        room = data.get('room', SOCKET_ROOMS['default'])
        message = data.get('message', '')
        
        print(f"Message received in room {room} from {username}: {message}")
        
        for room_sessions in active_sessions.values():
            for session in room_sessions:
                if session.get('sid') == request.sid:
                    session['last_active'] = time.time()
        
        # Emit response
        emit('response', json.dumps({'data': message, 'sender': username}), room=room)
    
    @socketio.on('get_sessions')
    def handle_get_sessions(data=None):
        """Handle request for active sessions"""
        room_filter = data.get('room') if data else None
        sessions = get_active_sessions(room_filter)
        
        emit(SOCKET_EVENTS['session_list'], {'sessions': sessions})
    
    @socketio.on('send_to_client')
    def handle_send_to_client(data):
        """Handle sending content to a specific client"""
        target_sid = data.get('sid')
        content = data.get('content')
        
        if not target_sid or not content:
            return
        
        socketio.emit(SOCKET_EVENTS['standard_response'], content, room=target_sid)
        print(f"Sent content to client SID: {target_sid}")

__all__ = ['SOCKET_ROOMS', 'SOCKET_EVENTS', 'active_sessions', 'emit_to_room', 
           'emit_to_client', 'get_active_sessions', 'register_socket_events']