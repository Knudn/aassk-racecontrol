import os
import time
import sqlite3
import requests
import logging
from logging.handlers import RotatingFileHandler

_log_dir = os.path.join(os.getcwd(), 'logs')
os.makedirs(_log_dir, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
    handlers=[
        RotatingFileHandler(os.path.join(_log_dir, 'event_monitor.log'), maxBytes=10_000_000, backupCount=5),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

DB_PATH = "site.db"

def get_location():
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        events_location = cur.execute("SELECT event_dir FROM global_config;").fetchall()
        return events_location[0][0]

def list_txt_files(directory):
    # List files in the specified directory without walking into subdirectories
    for file in os.listdir(directory):
        if file.endswith("Ex.scdb"):
            logger.info("Found: %s", os.path.join(directory, file))

def monitor_with_polling(directory):
    logger.info("Starting to monitor directory: %s", directory)
    last_mod_times = {}
    while True:
        for file in os.listdir(directory):
            if file.endswith("Ex.scdb"):
                file_path = os.path.join(directory, file)
                try:
                    current_mod_time = os.path.getmtime(file_path)
                except FileNotFoundError:
                    # File might have been deleted or moved; handle this if needed
                    if file in last_mod_times:
                        logger.warning("File '%s' was deleted or moved.", file_path)
                        del last_mod_times[file]
                    continue

                if file not in last_mod_times:
                    logger.info("Monitoring: %s", file_path)
                elif last_mod_times[file] != current_mod_time:
                    logger.info("Changed: %s", file_path)
                    rsp = requests.get("http://127.0.0.1:7777/api/active_event_update")
                    logger.debug("Update response: %s", rsp.text)
                
                last_mod_times[file] = current_mod_time
        time.sleep(2)  # Check every 10 seconds

if __name__ == "__main__":
    event_location = get_location()
    list_txt_files(event_location)  # Initial listing of .txt files
    monitor_with_polling(event_location)
