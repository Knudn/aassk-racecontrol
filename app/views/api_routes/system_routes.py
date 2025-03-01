# app/api/system_routes.py
from flask import request, current_app
from app.lib.utils import GetEnv, manage_process_screen
import requests

def register_system_routes(api_bp):
    """Register all system-related routes with the API blueprint"""
    
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