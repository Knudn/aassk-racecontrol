# app/config/websocket_config.py
# Configuration file for websocket rooms and events
from flask_socketio import emit

# Socket room definitions
SOCKET_ROOMS = {
    'default': 'room1',
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
    
    socketio.emit(SOCKET_EVENTS['standard_response'], data, room=room)

# Make sure the function is exported
__all__ = ['SOCKET_ROOMS', 'SOCKET_EVENTS', 'emit_to_room']