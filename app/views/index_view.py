
from flask import Blueprint, render_template, redirect
from app import socketio, join_room, emit


index_bp = Blueprint('index', __name__)

@index_bp.route('/')
def index():
    return redirect("/admin", code=302)

