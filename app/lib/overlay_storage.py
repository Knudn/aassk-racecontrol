"""
Disk-based storage for overlay groups.

Each group is a JSON file at data/overlays/<id>.json
Structure:
{
    "id": 1,
    "name": "Main Stream",
    "active_view_id": null,
    "next_view_id": 1,
    "views": [
        {
            "id": 1,
            "name": "Startlist",
            "next_widget_id": 1,
            "widgets": [
                {
                    "id": 1,
                    "file": "sample_standings.html",
                    "gs_x": 0, "gs_y": 0, "gs_w": 6, "gs_h": 6
                }
            ]
        }
    ]
}

Grid: 48 columns, 36 rows on a 1920x1080 canvas (default).
  40px per column, 30px per row at default resolution.
"""

import os
import json
import threading

OVERLAYS_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'overlays')
OVERLAYS_DIR = os.path.abspath(OVERLAYS_DIR)

GRID_COLS = 48
GRID_ROWS = 36

_lock = threading.Lock()


def _ensure_dir():
    os.makedirs(OVERLAYS_DIR, exist_ok=True)


def _group_path(group_id):
    return os.path.join(OVERLAYS_DIR, f'{group_id}.json')


def _read_group(group_id):
    path = _group_path(group_id)
    if not os.path.exists(path):
        return None
    with open(path, 'r') as f:
        group = json.load(f)

    _migrate_grid(group)
    return group


def _write_group(group):
    _ensure_dir()
    with open(_group_path(group['id']), 'w') as f:
        json.dump(group, f, indent=2)


def _next_group_id():
    _ensure_dir()
    max_id = 0
    for fname in os.listdir(OVERLAYS_DIR):
        if fname.endswith('.json'):
            try:
                gid = int(fname[:-5])
                if gid > max_id:
                    max_id = gid
            except ValueError:
                pass
    return max_id + 1


def _migrate_grid(group):
    """Migrate old 12x18 grid coords to 48x36."""
    if group.get('grid_version', 1) >= 2:
        _migrate_grid_v3(group)
        return False
    for v in group.get('views', []):
        for w in v.get('widgets', []):
            w['gs_x'] = w.get('gs_x', 0) * 4
            w['gs_y'] = w.get('gs_y', 0) * 2
            w['gs_w'] = w.get('gs_w', 6) * 4
            w['gs_h'] = w.get('gs_h', 6) * 2
    group['grid_version'] = 2
    _migrate_grid_v3(group)
    _write_group(group)
    return True


def _migrate_grid_v3(group):
    """Migrate 48x36 grid units to percentage-based positioning (0-100 floats)."""
    if group.get('grid_version', 1) >= 3:
        return False
    for v in group.get('views', []):
        for w in v.get('widgets', []):
            w['gs_x'] = round(w.get('gs_x', 0) / GRID_COLS * 100, 4)
            w['gs_y'] = round(w.get('gs_y', 0) / GRID_ROWS * 100, 4)
            w['gs_w'] = round(w.get('gs_w', GRID_COLS // 2) / GRID_COLS * 100, 4)
            w['gs_h'] = round(w.get('gs_h', GRID_ROWS // 3) / GRID_ROWS * 100, 4)
    group['grid_version'] = 3
    _write_group(group)
    return True


def _find_view(group, view_id):
    for v in group.get('views', []):
        if v['id'] == view_id:
            return v
    return None


# --- Groups ---

def list_groups():
    _ensure_dir()
    groups = []
    for fname in sorted(os.listdir(OVERLAYS_DIR)):
        if fname.endswith('.json'):
            with open(os.path.join(OVERLAYS_DIR, fname), 'r') as f:
                g = json.load(f)
                _migrate_grid(g)   # also calls _migrate_grid_v3 internally
                groups.append({
                    'id': g['id'],
                    'name': g['name'],
                    'active_view_id': g.get('active_view_id'),
                    'res_w': g.get('res_w', 1920),
                    'res_h': g.get('res_h', 1080)
                })
    return groups


def get_group(group_id):
    return _read_group(group_id)


def create_group(name):
    with _lock:
        gid = _next_group_id()
        group = {
            'id': gid,
            'name': name,
            'active_view_id': None,
            'next_view_id': 1,
            'res_w': 1920,
            'res_h': 1080,
            'grid_version': 3,
            'views': []
        }
        _write_group(group)
        return group


def update_group(group_id, data):
    with _lock:
        group = _read_group(group_id)
        if not group:
            return None
        for key in ['name', 'active_view_id', 'res_w', 'res_h']:
            if key in data:
                group[key] = data[key]
        _write_group(group)
        return group


def delete_group(group_id):
    path = _group_path(group_id)
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


# --- Views ---

def list_views(group_id):
    group = _read_group(group_id)
    if not group:
        return []
    return group.get('views', [])


def get_view(group_id, view_id):
    group = _read_group(group_id)
    if not group:
        return None
    return _find_view(group, view_id)


def create_view(group_id, name):
    with _lock:
        group = _read_group(group_id)
        if not group:
            return None
        vid = group.get('next_view_id', 1)
        group['next_view_id'] = vid + 1
        view = {
            'id': vid,
            'name': name,
            'next_widget_id': 1,
            'bg_color': '',
            'bg_image': '',
            'bg_opacity': 1.0,
            'widgets': []
        }
        group.setdefault('views', []).append(view)
        _write_group(group)
        return view


def update_view(group_id, view_id, data):
    with _lock:
        group = _read_group(group_id)
        if not group:
            return None
        view = _find_view(group, view_id)
        if not view:
            return None
        for key in ['name', 'bg_color', 'bg_image', 'bg_opacity']:
            if key in data:
                view[key] = data[key]
        _write_group(group)
        return view


def delete_view(group_id, view_id):
    with _lock:
        group = _read_group(group_id)
        if not group:
            return False
        group['views'] = [v for v in group.get('views', []) if v['id'] != view_id]
        if group.get('active_view_id') == view_id:
            group['active_view_id'] = None
        _write_group(group)
        return True


# --- Widgets ---

def list_widgets(group_id, view_id):
    group = _read_group(group_id)
    if not group:
        return []
    view = _find_view(group, view_id)
    if not view:
        return []
    return view.get('widgets', [])


def create_widget(group_id, view_id, data):
    with _lock:
        group = _read_group(group_id)
        if not group:
            return None
        view = _find_view(group, view_id)
        if not view:
            return None
        wid = view.get('next_widget_id', 1)
        view['next_widget_id'] = wid + 1
        is_fs = bool(data.get('fullscreen', False))
        widget = {
            'id': wid,
            'file': data.get('file', ''),
            'url': data.get('url', ''),
            'params': data.get('params', ''),
            'fullscreen': is_fs,
            'gs_x': 0.0 if is_fs else data.get('gs_x', 0.0),
            'gs_y': 0.0 if is_fs else data.get('gs_y', 0.0),
            'gs_w': 100.0 if is_fs else data.get('gs_w', 25.0),
            'gs_h': 100.0 if is_fs else data.get('gs_h', 25.0)
        }
        view.setdefault('widgets', []).append(widget)
        _write_group(group)
        return widget


def update_widget(group_id, view_id, widget_id, data):
    with _lock:
        group = _read_group(group_id)
        if not group:
            return None
        view = _find_view(group, view_id)
        if not view:
            return None
        for w in view.get('widgets', []):
            if w['id'] == widget_id:
                for key in ['file', 'url', 'params', 'fullscreen', 'gs_x', 'gs_y', 'gs_w', 'gs_h']:
                    if key in data:
                        w[key] = data[key]
                if w.get('fullscreen'):
                    w['gs_x'] = 0.0; w['gs_y'] = 0.0; w['gs_w'] = 100.0; w['gs_h'] = 100.0
                _write_group(group)
                return w
        return None


def delete_widget(group_id, view_id, widget_id):
    with _lock:
        group = _read_group(group_id)
        if not group:
            return False
        view = _find_view(group, view_id)
        if not view:
            return False
        view['widgets'] = [w for w in view.get('widgets', []) if w['id'] != widget_id]
        _write_group(group)
        return True


# --- Switch view ---

def switch_view(group_id, view_id):
    with _lock:
        group = _read_group(group_id)
        if not group:
            return None
        if view_id is not None and not _find_view(group, view_id):
            return None
        group['active_view_id'] = view_id
        _write_group(group)
        return group


# --- Grid to pixel ---
# gs_x/y/w/h are now percentage values (0.0–100.0) of the canvas dimensions.

def grid_to_px(gs_x, gs_y, gs_w, gs_h, res_w=1920, res_h=1080):
    return {
        'x': gs_x / 100 * res_w,
        'y': gs_y / 100 * res_h,
        'w': gs_w / 100 * res_w,
        'h': gs_h / 100 * res_h,
    }
