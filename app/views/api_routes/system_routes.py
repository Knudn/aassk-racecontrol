# app/api/system_routes.py
from flask import request, current_app, render_template
from app.lib.utils import GetEnv, manage_process_screen
import requests
from app.config.websocket_config import emit_to_room, SOCKET_ROOMS
from app import socketio, mqtt_client

def register_system_routes(api_bp):
    """Register all system-related routes with the API blueprint"""


    # Helper function for sending data to a socket room
    #@api_bp.route('/api/send_data')
    #def send_data_to_room(msg, room=None):
    #    """Sends data to a specified socket room"""
    #    if request.args.get('room'):
    #        room = request.args.get('room')
    #    elif room is None:
    #        room = SOCKET_ROOMS['default']
    #        
    #    emit_to_room(socketio, msg, room)
    #    return {"message": f"Data sent to room: {room}"}

    @api_bp.route('/api/restart', methods=['GET', 'POST'])
    def restart():
        result = manage_process_screen("cross_clock_server.py", "restart")
        current_app.logger.info(f"Restart result: {result}")
        return {"status": "success", "message": "Service restarted"}
    
    @api_bp.route('/api/stop', methods=['GET', 'POST'])
    def stop():
        result = manage_process_screen("cross_clock_server.py", "stop")
        current_app.logger.info(f"Stop result: {result}")
        return {"status": "success", "message": "Service stopped"}
    
    @api_bp.route('/api/start', methods=['GET', 'POST'])
    def start():
        result = manage_process_screen("cross_clock_server.py", "start")
        current_app.logger.info(f"Start result: {result}")
        return {"status": "success", "message": "Service started"}


    @api_bp.route('/api/test', methods=['GET', 'POST'])
    def test():
        import json
        from app.lib.utils import get_upcoming_drivers

        if not GetEnv()["cross"]: 
            data = get_upcoming_drivers(return_driver_context=True)
        else:
            data = None

        return data
        
