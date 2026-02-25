from urllib.parse import urlencode
from flask import Blueprint, render_template, abort
from app.lib.overlay_storage import get_group, grid_to_px


def _build_params(params_str):
    """Convert 'key=val, key2=val2' to '?key=val&key2=val2'."""
    if not params_str or not params_str.strip():
        return ''
    pairs = {}
    for part in params_str.split(','):
        kv = part.strip().split('=', 1)
        if len(kv) == 2 and kv[0].strip():
            pairs[kv[0].strip()] = kv[1].strip()
    return '?' + urlencode(pairs) if pairs else ''

overlay_bp = Blueprint('overlay', __name__)


@overlay_bp.route('/overlay/<int:group_id>')
def overlay_output(group_id):
    group = get_group(group_id)
    if not group:
        abort(404)

    widgets = []
    active_view = None

    if group.get('active_view_id'):
        for v in group.get('views', []):
            if v['id'] == group['active_view_id']:
                active_view = v
                break
        if active_view:
            rw = group.get('res_w', 1920)
            rh = group.get('res_h', 1080)
            for w in active_view.get('widgets', []):
                pw = dict(w)
                pw['px'] = grid_to_px(w.get('gs_x', 0), w.get('gs_y', 0),
                                      w.get('gs_w', 6), w.get('gs_h', 6), rw, rh)
                base = pw.get('url') or ('/vmix/raw/' + pw.get('file', ''))
                pw['src'] = base + _build_params(pw.get('params', ''))
                widgets.append(pw)

    return render_template('overlay/output.html', group=group, widgets=widgets,
                           view=active_view)
