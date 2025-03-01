import os
import time
import shutil
from datetime import datetime
import json
import fcntl
import sqlite3
import requests


FIFO_PATH = '/tmp/file_monitor_fifo'
ACTIVE_EVENT_QUERY = "SELECT C_VALUE FROM TPARAMETERS WHERE C_PARAM = 'HEAT' OR C_PARAM = 'EVENT';"
MODE_QUERY = "SELECT C_VALUE FROM TPARAMETERS WHERE C_PARAM='MODULE';"

STARTLIST_DICT = []
ACTIVE_STATE = {"event":0, "heat":0, "mode":0}

ACTIVE_EVENT = ""

with sqlite3.connect("site.db") as con:
    cur = con.cursor()
        
    use_inter = cur.execute("SELECT use_intermediate from global_config;").fetchone()[0]
    host = cur.execute("SELECT params FROM microservices WHERE path = 'msport_display_proxy.py';").fetchone()[0]
    if str(host) == str("0.0.0.0"):
        host = "localhost"

def create_fifo():
    if not os.path.exists(FIFO_PATH):
        os.mkfifo(FIFO_PATH)

def open_fifo():
    try:
        fd = os.open(FIFO_PATH, os.O_WRONLY | os.O_NONBLOCK)
        return os.fdopen(fd, 'w')
    except OSError:
        return None

def list_files(directory):
    return [item.path for item in os.scandir(directory) if item.is_file()]

def get_file_modification_time(file_path):
    try:
        return os.path.getmtime(file_path)
    except FileNotFoundError:
        print(f"File not found: {file_path}")
        return None
    except Exception as e:
        print(f"Error checking file {file_path}: {e}")
        return None

def copy_file(src, dest):
    try:
        shutil.copy2(src, dest)
        print(f"Copied {src} to {dest}")
        return True
    except Exception as e:
        print(f"Error copying file {src} to {dest}: {e}")
        return False

def notify_change(fifo, file_path):
    if fifo:
        try:
            file_name = os.path.basename(file_path)
            message = file_name
            print(file_name)
            if "Ex" in file_name or file_name == "Online.scdb":
                
                fcntl.flock(fifo, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fifo.write(message + '\n')
                fifo.flush()
                fcntl.flock(fifo, fcntl.LOCK_UN)
                print(f"Notified change for {file_name}")
        except BlockingIOError:
            print("No FIFO reader available. Skipping notification.")
        except Exception as e:
            print(f"Error writing to FIFO: {e}")

def monitor_files(source_dir, intermediate_dir, use_fifo=False, interval=1):
    files = list_files(source_dir)
    last_modified_times = {file: None for file in files}
    fifo = None

    if use_fifo:
        create_fifo()

    try:
        while True:
            if use_fifo and fifo is None:
                fifo = open_fifo()

            for file in files:
                current_mtime = get_file_modification_time(file)
                
                if current_mtime is None:
                    continue
                
                if last_modified_times[file] is None or current_mtime > last_modified_times[file]:
                    update = False
                    #print(f"File changed: {file} at {datetime.fromtimestamp(current_mtime)}")
                    dest_path = os.path.join(intermediate_dir, os.path.basename(file))
                    filename = os.path.basename(file)
                    db_file = filename.split('.')[0].replace("scdb", "")


                    if copy_file(file, dest_path):
                        if use_fifo:
                            notify_change(fifo, file)
                        last_modified_times[file] = current_mtime
                    
                    if db_file == "Online":
                        try: 
                            with sqlite3.connect(intermediate_dir+"/Online.scdb") as conn:
                                cursor = conn.cursor()
                                cursor.execute(ACTIVE_EVENT_QUERY)
                                active_data = cursor.fetchall()
                                
                                event = active_data[0][0]
                                heat = active_data[1][0]
                                requests.get("http://{host}:7777/api/active_event_update".format(host=host))

                                

                            if event.zfill(3) != ACTIVE_STATE["event"]:
                                ACTIVE_STATE["event"] = event.zfill(3)
                                ACTIVE_STATE["heat"] = heat

                                STARTLIST_DICT = []

                                with sqlite3.connect(intermediate_dir+"/Event"+ACTIVE_STATE["event"]+".scdb") as conn:
                                    cursor = conn.cursor()
                                    cursor.execute(MODE_QUERY)
                                    mode = cursor.fetchall()[0][0]
                                    ACTIVE_STATE["mode"] = mode

                        except Exception as e:
                            print(e)
                            print("Could not access online file")

                    if db_file == "Event{0}Ex".format(ACTIVE_STATE["event"]):
                        
                        try:
                            starters = False
                            STARTLIST_DICT = []
                            query = "SELECT C_NUM, C_INTER1, C_INTER2, C_INTER3, C_SPEED1, C_STATUS, C_TIME FROM TTIMEINFOS_HEAT{0}".format(ACTIVE_STATE["heat"])

                            with sqlite3.connect(intermediate_dir+"/Event"+ACTIVE_STATE["event"]+"Ex"+".scdb") as conn:
                                cursor = conn.cursor()
                                cursor.execute(query)
                                time_data = cursor.fetchall()
                                #STARTLIST_DICT
                                send_update = True
                                for a in time_data:
                                    if a[1] == 0 and a[2] == 0 and a[3] == 0 and a[4] == 0 and a[5] == 0 and a[6] == 0:
                                        STARTLIST_DICT.append({"CID":a[0], "STATUS":"STARTED"})




                                        starters = False
                                        send_update = False
                                    else:

                                        STARTLIST_DICT.append({"CID":a[0], "STATUS":"FINISHED"})


                                
                                if int(mode) == int(0):

                                    if starters == False:
                                        requests.get("http://{host}:7777/api/active_event_update".format(host=host))
                                else:

                                    if str(use_inter) == str(1):
                                        if send_update == True:
                                            requests.get("http://{host}:7777/api/active_event_update".format(host=host))
                                            
                                url = "http://{host}:7777/api/start_status".format(host=host)
                                headers = {
                                    'Content-Type': 'application/json'
                                }
                                
                                response = requests.post(url, json=STARTLIST_DICT, headers=headers)
                                
                                
                        except Exception as e:
                            print(e)

            time.sleep(interval)
    finally:
        if fifo:
            fifo.close()

def main():
    source_directory = '/mnt/test'
    intermediate_directory = '/mnt/intermediate'
    use_fifo = False
    monitor_files(source_directory, intermediate_directory, use_fifo)

if __name__ == "__main__":
    main()