# app/config/websocket_config.py
from flask_socketio import emit, join_room
from flask import request
import json
from collections import defaultdict
import time
from app import socketio

# Socket room definitions
SOCKET_ROOMS = {
    'default': 'default',
    'clock_management': 'clock_mgnt',
    'retry_notifications': 'socket_retry',
    'infoscreen': 'infoscreen',
    'admin': 'admin',
    'prestage_lights': 'prestage_lights',

}

# Socket event types
SOCKET_EVENTS = {
    'standard_response': 'response',
    'admin_update': 'admin_update',
    'session_list': 'session_list'
}

# In-memory storage for active sessions
active_sessions = defaultdict(list)

def send_data_to_room(msg, room=None):
    """Sends data to a specified socket room"""
    if request.args.get('room'):
        room = request.args.get('room')
    elif room is None:
        room = SOCKET_ROOMS['default']
        
    emit_to_room(socketio, msg, room)
    return {"message": f"Data sent to room: {room}"}


# Function to emit data to a specific room
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
    
    # Make sure data is serialized to JSON if it's not already a string
    if not isinstance(data, str):
        data = json.dumps(data)
    
    socketio.emit(SOCKET_EVENTS['standard_response'], data, room=room)

# Function to emit data to a specific client by SID
def emit_to_client(socketio, data, sid):
    """
    Emits data to a specific client by SID
    
    Args:
        socketio: Flask-SocketIO instance
        data: Data to emit
        sid: Client's session ID
    """
    # Make sure data is serialized to JSON if it's not already a string
    if not isinstance(data, str):
        data = json.dumps(data)
    
    socketio.emit(SOCKET_EVENTS['standard_response'], data, room=sid)

# Function to get all active sessions
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
    
    # Get all sessions from all rooms
    all_sessions = []
    for room_name, sessions in active_sessions.items():
        for session in sessions:
            session_copy = session.copy()
            session_copy['room'] = room_name
            all_sessions.append(session_copy)
    
    return all_sessions

# Socket event handlers
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
        # Remove from active sessions
        for room in active_sessions:
            active_sessions[room] = [session for session in active_sessions[room] 
                                    if session.get('sid') != request.sid]
        
        # Notify admin about the change
        socketio.emit(SOCKET_EVENTS['admin_update'], {'action': 'disconnect', 'sid': request.sid}, 
                     room=SOCKET_ROOMS['admin'])
        print(f"Client disconnected with SID: {request.sid}")
    
    @socketio.on('join')
    def on_join(data):
        """Handle client joining a room"""
        username = data.get('username', 'anonymous')
        room = data.get('room', SOCKET_ROOMS['default'])
        hostname = data.get('hostname', 'unknown')

        # Join the requested room
        join_room(room)
        
        # Store session info
        session_info = {
            'sid': request.sid,
            'username': username,
            'hostname': hostname,
            'ip': request.remote_addr,
            'user_agent': request.headers.get('User-Agent', 'unknown'),
            'connected_at': time.time(),
            'last_active': time.time()
        }
        
        # Check if this session already exists
        exists = False
        for i, session in enumerate(active_sessions[room]):
            if session.get('sid') == request.sid:
                active_sessions[room][i] = session_info
                exists = True
                break
        
        if not exists:
            active_sessions[room].append(session_info)
        
        print(f"Client {username} (SID: {request.sid}) joined room: {room}")
        
        # Send confirmation to the client
        emit('joined', {'status': 'success', 'room': room, 'session_id': request.sid})
        
        # If this is an infoscreen client, notify admin
        if room == SOCKET_ROOMS['infoscreen']:
            socketio.emit(SOCKET_EVENTS['admin_update'], 
                         {'action': 'join', 'session': session_info}, 
                         room=SOCKET_ROOMS['admin'])
    
    @socketio.on('message')
    def handle_message(data):
        """Handle incoming messages"""
        username = data.get('username', 'anonymous')
        room = data.get('room', SOCKET_ROOMS['default'])
        message = data.get('message', '')
        
        print(f"Message received in room {room} from {username}: {message}")
        
        # Update last active timestamp
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
        
        # Send session list to requester
        emit(SOCKET_EVENTS['session_list'], {'sessions': sessions})
    
    @socketio.on('send_to_client')
    def handle_send_to_client(data):
        """Handle sending content to a specific client"""
        target_sid = data.get('sid')
        content = data.get('content')
        
        if not target_sid or not content:
            return
        
        # Send content to target client
        socketio.emit(SOCKET_EVENTS['standard_response'], content, room=target_sid)
        print(f"Sent content to client SID: {target_sid}")

# Make sure all necessary functions are exported
__all__ = ['SOCKET_ROOMS', 'SOCKET_EVENTS', 'active_sessions', 'emit_to_room', 
           'emit_to_client', 'get_active_sessions', 'register_socket_events']