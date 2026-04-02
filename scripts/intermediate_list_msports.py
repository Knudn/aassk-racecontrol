import os
import sys
import time
import sqlite3
import logging
from logging.handlers import RotatingFileHandler

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.lib.db_func import insert_msports_data

_log_dir = os.path.join(os.getcwd(), 'logs')
os.makedirs(_log_dir, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
    handlers=[
        RotatingFileHandler(os.path.join(_log_dir, 'intermediate_list_msports.log'), maxBytes=10_000_000, backupCount=5),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

DB_PATH = "site.db"

with sqlite3.connect(DB_PATH) as _con:
    _row = _con.cursor().execute(
        "SELECT msport_tm, event_dir FROM global_config;"
    ).fetchone()

if not bool(_row[0]):
    logger.info("msport_tm is not enabled in global config. Exiting.")
    sys.exit()

WATCH_DIR = _row[1]
logger.info("Watching: %s", WATCH_DIR)

tracking = {}

while True:
    try:
        with os.scandir(WATCH_DIR) as entries:
            for entry in entries:
                if not entry.name.endswith(".scdb"):
                    continue
                if "ex" in entry.name.lower():
                    continue

                mtime = entry.stat().st_mtime
                if tracking.get(entry.path, 0) >= mtime:
                    continue
                tracking[entry.path] = mtime

                logger.info("Change detected: %s", entry.name)
                #insert_msports_data(lookup_active=True)

    except Exception as e:
        logger.error("Error: %s", e)

    time.sleep(0.5)
