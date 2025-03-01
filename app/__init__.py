from flask import Flask, jsonify
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from app.lib.db_operation import map_database_files
from flask_socketio import SocketIO, join_room, emit
from os import getcwd, path

# Initialize SQLAlchemy and SocketIO with no settings
db = SQLAlchemy()
socketio = SocketIO()

def create_app():
    app = Flask(__name__)
    CORS(app)
    app.secret_key = 'your_secret_key'
    pwd = getcwd()
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + path.join(pwd, 'site.db')
    app.config['SECRET_KEY'] = 'your_secret_key'


    db.init_app(app)
    socketio.init_app(app)

    from app.views.index_view import index_bp
    from app.views.admin_view import admin_bp
    from app.views.api_view import api_bp
    from app.views.vmix_view import vmix_bp
    from app.views.board_view import board_bp
    from app.views.cross_view import cross_bp
    from app.views.home_view import home_bp

    app.register_blueprint(index_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(vmix_bp)
    app.register_blueprint(board_bp)
    app.register_blueprint(cross_bp)
    app.register_blueprint(home_bp)

    app.jinja_env.filters['tojson'] = jsonify
    
    return app, socketio
