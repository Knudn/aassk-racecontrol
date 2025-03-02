
from flask import Blueprint, redirect

index_bp = Blueprint('index', __name__)

@index_bp.route('/')
def index():
    return redirect("/admin", code=302)

