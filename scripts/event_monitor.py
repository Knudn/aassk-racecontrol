import os
import time
import sqlite3
import requests

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
            print(os.path.join(directory, file))

def monitor_with_polling(directory):
    print(f"Starting to monitor directory: {directory}")
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
                        print(f"File '{file_path}' was deleted or moved.")
                        del last_mod_times[file]
                    continue

                if file not in last_mod_times:
                    print(f"File '{file_path}' is being monitored.")
                elif last_mod_times[file] != current_mod_time:
                    print(f"File '{file_path}' was changed.")
                    rsp = requests.get("http://127.0.0.1:7777/api/active_event_update")
                    print(rsp.text)
                
                last_mod_times[file] = current_mod_time
        time.sleep(2)  # Check every 10 seconds

if __name__ == "__main__":
    event_location = get_location()
    list_txt_files(event_location)  # Initial listing of .txt files
    monitor_with_polling(event_location)
