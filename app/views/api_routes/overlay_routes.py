import os
import json
from flask import request, jsonify
from app import socketio
from app.config.websocket_config import SOCKET_EVENTS
from app.lib.overlay_storage import (
    list_groups, get_group, create_group, update_group, delete_group,
    list_views, get_view, create_view, update_view, delete_view,
    list_widgets, create_widget, update_widget, delete_widget,
    switch_view
)


def register_overlay_routes(api_bp):

    # --- Groups ---

    @api_bp.route('/api/overlay/groups', methods=['GET', 'POST'])
    def overlay_groups():
        if request.method == 'GET':
            return jsonify(list_groups())
        data = request.get_json()
        return jsonify(create_group(data.get('name', 'New Group'))), 201

    @api_bp.route('/api/overlay/groups/<int:gid>', methods=['GET', 'PUT', 'DELETE'])
    def overlay_group_detail(gid):
        if request.method == 'GET':
            g = get_group(gid)
            return jsonify(g) if g else (jsonify({'error': 'Not found'}), 404)
        if request.method == 'DELETE':
            return jsonify({'ok': delete_group(gid)})
        g = update_group(gid, request.get_json())
        return jsonify(g) if g else (jsonify({'error': 'Not found'}), 404)

    # --- Views ---

    @api_bp.route('/api/overlay/groups/<int:gid>/views', methods=['GET', 'POST'])
    def overlay_views(gid):
        if request.method == 'GET':
            return jsonify(list_views(gid))
        data = request.get_json()
        v = create_view(gid, data.get('name', 'New View'))
        return jsonify(v) if v else (jsonify({'error': 'Group not found'}), 404)

    @api_bp.route('/api/overlay/groups/<int:gid>/views/<int:vid>', methods=['GET', 'PUT', 'DELETE'])
    def overlay_view_detail(gid, vid):
        if request.method == 'GET':
            v = get_view(gid, vid)
            return jsonify(v) if v else (jsonify({'error': 'Not found'}), 404)
        if request.method == 'DELETE':
            return jsonify({'ok': delete_view(gid, vid)})
        v = update_view(gid, vid, request.get_json())
        return jsonify(v) if v else (jsonify({'error': 'Not found'}), 404)

    # --- Widgets ---

    @api_bp.route('/api/overlay/groups/<int:gid>/views/<int:vid>/widgets', methods=['GET', 'POST'])
    def overlay_widgets(gid, vid):
        if request.method == 'GET':
            return jsonify(list_widgets(gid, vid))
        data = request.get_json()
        w = create_widget(gid, vid, data)
        return jsonify(w) if w else (jsonify({'error': 'Not found'}), 404)

    @api_bp.route('/api/overlay/groups/<int:gid>/views/<int:vid>/widgets/<int:wid>', methods=['PUT', 'DELETE'])
    def overlay_widget_detail(gid, vid, wid):
        if request.method == 'DELETE':
            return jsonify({'ok': delete_widget(gid, vid, wid)})
        w = update_widget(gid, vid, wid, request.get_json())
        return jsonify(w) if w else (jsonify({'error': 'Not found'}), 404)

    # --- List available vmix files ---

    @api_bp.route('/api/overlay/vmix-files', methods=['GET'])
    def overlay_vmix_files():
        vmix_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'templates', 'vmix')
        vmix_dir = os.path.abspath(vmix_dir)
        files = []
        if os.path.isdir(vmix_dir):
            for root_dir, dirs, fnames in os.walk(vmix_dir):
                for f in fnames:
                    if f.endswith('.html'):
                        rel = os.path.relpath(os.path.join(root_dir, f), vmix_dir)
                        files.append(rel)
        return jsonify(sorted(files))

    # --- Switch active view ---

    @api_bp.route('/api/overlay/groups/<int:gid>/switch', methods=['GET', 'POST'])
    def overlay_switch_view(gid):
        if request.method == 'GET':
            view_id_str = request.args.get('view_id')
            view_id = int(view_id_str) if view_id_str and view_id_str != 'null' else None
        else:
            data = request.get_json()
            view_id = data.get('view_id')
        group = switch_view(gid, view_id)
        if not group:
            return jsonify({'error': 'Not found'}), 404
        room = f'overlay_{gid}'
        socketio.emit(SOCKET_EVENTS['standard_response'],
                      json.dumps({'action': 'switch_view', 'view_id': view_id, 'group_id': gid}),
                      room=room)
        return jsonify({'status': 'switched', 'active_view_id': view_id})

    # --- List views for a group (id + name) ---

    @api_bp.route('/api/overlay/groups/<int:gid>/views/list', methods=['GET'])
    def overlay_views_list(gid):
        views = list_views(gid)
        return jsonify([{'id': v['id'], 'name': v['name']} for v in views])
