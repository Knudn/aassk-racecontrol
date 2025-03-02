import os

# Base application settings
APP_NAME = "Åseral"
DEBUG = True
PORT = 7777
DEFAULT_HOST = "0.0.0.0"

# Logging configuration
LOG_LEVEL = "INFO"
LOG_DIRECTORY = os.path.join(os.getcwd(), 'logs')
LOG_FILE = os.path.join(LOG_DIRECTORY, 'app.log')
LOG_FORMAT = '[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
LOG_MAX_BYTES = 10000000
LOG_BACKUP_COUNT = 5

# Paths
PWD = os.getcwd()
PROJECT_DIR = PWD + "/"
DB_LOCATION = PWD + "/data/event_db/"
EVENT_DIR = "/mnt/test/"
INFOSCREEN_ASSET_PATH = "/app/static/assets/infoscreen"
INTERMEDIATE_PATH = "/mnt/intermediate/"

# Database defaults
DEFAULT_GLOBAL_CONFIG = {
    "session_name": "Åseral",
    "project_dir": PROJECT_DIR,
    "db_location": DB_LOCATION,
    "event_dir": EVENT_DIR,
    "wl_title": "Eikerapen",
    "infoscreen_asset_path": INFOSCREEN_ASSET_PATH,
    "intermediate_path": INTERMEDIATE_PATH,
    "hard_event_dir": EVENT_DIR,
    "autocommit": True,
    "use_intermediate": True
}

DEFAULT_SPEAKER_PAGE_SETTINGS = {
    "match_parrallel": False
}

DEFAULT_ARCHIVE_SERVER = {
    "hostname": "192.168.20.218:5000",
    "auth_token": "1234",
    "use_use_token": True,
    "state": False,
    "enabled": False
}

# LED Panel configurations
DEFAULT_LED_PANELS = [
    {"endpoint": "192.168.20.219", "active_playlist": "none", "brightness": 100},
    {"endpoint": "192.168.20.220", "active_playlist": "none", "brightness": 100}
]

# Microservices configuration
DEFAULT_MICROSERVICES = [
    {"name": "Msport Proxy", "path": "msport_display_proxy.py", "params": "{host}"},
    {"name": "Cross Clock Server", "path": "cross_clock_server.py", "params": "None"},
    {"name": "Backup Clock", "path": "clock_server_vola.py", "params": "192.168.1.51"},
    {"name": "PDF Converter", "path": "pdf_converter.py", "params": "None"},
    {"name": "Intermediate Listener", "path": "intermediate_list.py", "params": "None"}
]

# InfoScreen asset templates - {ip} will be replaced with actual IP
INFOSCREEN_ASSETS = [
    {"name": "Ladder Active", "asset": "http://{ip}:7777/board/ladder"},
    {"name": "Ladder loop 8", "asset": "http://{ip}:7777/board/ladder/loop?timer=8"},
    {"name": "Ladder loop 15", "asset": "http://{ip}:7777/board/ladder/loop?timer=15"},
    {"name": "Startlist active upcoming", "asset": "http://{ip}:7777/board/startlist_simple_upcoming"},
    {"name": "Startlist active", "asset": "http://{ip}:7777/board/startlist_simple"},
    {"name": "Startlist loop stige 8", "asset": "http://{ip}:7777/board/startlist_simple_loop?event_filter=Stige&timer=8"},
    {"name": "Startlist loop stige 15", "asset": "http://{ip}:7777/board/startlist_simple_loop?event_filter=Stige&timer=15"},
    {"name": "Startlist loop kval 8", "asset": "http://{ip}:7777/board/startlist_simple_loop?event_filter=Kvalifisering&timer=8"},
    {"name": "Startlist loop kval 15", "asset": "http://{ip}:7777/board/startlist_simple_loop?event_filter=Kvalifisering&timer=15"},
    {"name": "Startlist loop finale 8", "asset": "http://{ip}:7777/board/startlist_simple_loop_single?event_filter=Finale&timer=8"},
    {"name": "Startlist loop finale 15", "asset": "http://{ip}:7777/board/startlist_simple_loop_single?event_filter=Finale&timer=15"},
    {"name": "Startlist Cross Active", "asset": "http://{ip}:7777/board/startlist_active_simple_single"},
    {"name": "Startlist Cross Active Upcoming", "asset": "http://{ip}:7777/board/startlist_active_simple_single?upcoming=true"},                
    {"name": "Scoreboard loop 8", "asset": "http://{ip}:7777/board/scoreboard_c?columns=3&timer=8"},
    {"name": "Scoreboard loop 15", "asset": "http://{ip}:7777/board/scoreboard_c?columns=3&timer=15"},
    {"name": "Scoreboard cross all", "asset": "http://{ip}:7777/board/scoreboard_cross?all=all"},
    {"name": "Scoreboard cross event", "asset": "http://{ip}:7777/board/scoreboard_cross?active=true"}
]