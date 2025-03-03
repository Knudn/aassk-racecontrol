# app/config/websocket_config.py
# Configuration file for websocket rooms and events
from flask_socketio import emit, join_room
from flask import request
import json

# Socket room definitions
SOCKET_ROOMS = {
    'default': 'default',
    'clock_management': 'clock_mgnt',
    'retry_notifications': 'socket_retry'
}

# Socket event types
SOCKET_EVENTS = {
    'standard_response': 'response'
}

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
    
    @socketio.on('join')
    def on_join(data):
        """Handle client joining a room"""
        username = data.get('username', 'anonymous')
        room = data.get('room', SOCKET_ROOMS['default'])
        
        # Join the requested room
        join_room(room)
        print(f"Client {username} (SID: {request.sid}) joined room: {room}")
        
        # Send confirmation to the client
        emit('joined', {'status': 'success', 'room': room}, room=room)
    
    @socketio.on('message')
    def handle_message(data):
        """Handle incoming messages"""
        print("Message received:", data)
        username = data.get('username', 'anonymous')
        room = data.get('room', SOCKET_ROOMS['default'])
        message = data.get('message', '')
        print(f"Message received in room {room} from {username}: {message}")
        
        # Ensure we're emitting to the correct event type that client is listening for
        emit('response', json.dumps({'data': message, 'sender': username}), room=room)

# Make sure all necessary functions are exported
__all__ = ['SOCKET_ROOMS', 'SOCKET_EVENTS', 'emit_to_room', 'register_socket_events']