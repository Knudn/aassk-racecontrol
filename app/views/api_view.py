import app.config
from flask import Blueprint, request
import sqlite3
from app import socketio
from app.config.websocket_config import emit_to_room, SOCKET_ROOMS
from app.views.api_routes.event_routes import register_event_routes
from app.views.api_routes.driver_routes import register_driver_routes
from app.views.api_routes.timedata_routes import register_timedata_routes
from app.views.api_routes.archive_routes import register_archive_routes
from app.views.api_routes.system_routes import register_system_routes

# Create the main API blueprint
api_bp = Blueprint('api', __name__)

# Register each group of routes with the blueprint
def register_all_routes(api_blueprint):
    """Register all route groups with the main API blueprint"""
    register_event_routes(api_blueprint)
    register_driver_routes(api_blueprint)
    register_timedata_routes(api_blueprint)
    register_archive_routes(api_blueprint)
    register_system_routes(api_blueprint)

# Helper function for sending data to a socket room
@api_bp.route('/api/send_data')
def send_data_to_room(msg, room=None):
    """Sends data to a specified socket room"""
    if request.args.get('room'):
        room = request.args.get('room')
    elif room is None:
        room = SOCKET_ROOMS['default']
        
    emit_to_room(socketio, msg, room)
    return {"message": f"Data sent to room: {room}"}

# Initialize all routes
register_all_routes(api_bp)