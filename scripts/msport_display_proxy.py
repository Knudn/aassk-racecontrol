import asyncio
import websockets
import re
import json
import sqlite3
import logging
import requests
import socket
import time
import aiohttp
import string
import os


# Setting up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

current_working_directory = os.getcwd()
print(current_working_directory)


# Constants
DB_PATH = "site.db"
URL = 'http://localhost:10000/entry'


with sqlite3.connect(DB_PATH) as con:
    cur = con.cursor()

    listen_ip = cur.execute("SELECT params FROM microservices WHERE path = 'msport_display_proxy.py';").fetchone()[0]
    print(listen_ip)
    use_inter = cur.execute("SELECT use_intermediate from global_config;").fetchone()[0]

data_sock = {
    "Driver1": {"first_name": "", "last_name":"" , "time": "0", "bid":"0"},
    "Driver2": {"first_name": "", "last_name":"" , "time": "0", "bid":"0"}
}

driver_index = 0

refresh_triggers = ["DNS", "DSQ", "DNF"]

update_field = False

d_history = ""

d1_update = False
d2_update = False

old_main_driver = ""

async def async_update_event(listen_ip):
    async with aiohttp.ClientSession() as session:
        url = f"http://{listen_ip}:7777/api/active_event_update"
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    logging.info("Event update successful")
                else:
                    logging.error("Event update failed with status: %s", response.status)
        except Exception as e:
            logging.error("Failed to send update: %s", str(e))


class DatabaseHandler:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

    def update_driver(self, D1=None, D2=None):
        with self.conn as con:
            cur = con.cursor()
            try:
                if D1 is not None and D2 is not None:
                    cur.execute("UPDATE active_drivers SET D1 = ?, D2 = ?;", (D1, D2))
                elif D1 is not None:
                    cur.execute("UPDATE active_drivers SET D1 = ?;", (D1,))
                elif D2 is not None:
                    cur.execute("UPDATE active_drivers SET D2 = ?;", (D2,))
                con.commit()
            except sqlite3.Error as e:
                logging.error("SQLite error: %s", e)
            except Exception as e:
                logging.error("Exception in updating drivers: %s", str(e))
            finally:
                logging.info(cur.execute("SELECT * FROM active_drivers;").fetchall())

    def __del__(self):
        self.conn.close()



def strip_stx(input_string):
    # Remove the STX character (ASCII 2)
    return re.sub(r'\x02', '', input_string)

async def data_clean(data, db_handler):
    global d1_update
    global d2_update
    global old_main_driver

    update_event = False

    data_decoded = data.decode('iso-8859-1')
    
    data_decoded = strip_stx(data_decoded)
    data_new = str.splitlines(data_decoded)
    
    for b in data_new:
        #Driver_time D1
        if b[0] == "1":
            driver_1_time = b[2:].rstrip()
            if driver_1_time == "":
                continue

            if len(str(data_sock["Driver1"]["time"])) > 4:
                if (data_sock["Driver1"]["time"][-4] == ".") and driver_1_time in refresh_triggers:
                    update_event = True

            data_sock["Driver1"]["time"] = driver_1_time

            if data_sock["Driver1"]["time"] in refresh_triggers:
                d1_update = True
                print("Set D1 Update to True")
    
            elif len(str(data_sock["Driver1"]["time"])) > 4:
                if (data_sock["Driver1"]["time"][-4] == "."):
                    print("Set D1 Update to True, based on time")
                    d1_update = True
                
        elif b[0] == "2":
            driver_2_time = b[2:].rstrip()
            if driver_2_time == "":
                continue

            if len(str(data_sock["Driver2"]["time"])) > 4:
                if (data_sock["Driver2"]["time"][-4] == ".") and driver_2_time in refresh_triggers:
                    update_event = True

            data_sock["Driver2"]["time"] = driver_2_time

            if data_sock["Driver2"]["time"] in refresh_triggers:
                print("Set D2 Update to True")
                d2_update = True
    
            elif len(str(data_sock["Driver2"]["time"])) > 4:
                if (data_sock["Driver2"]["time"][-4] == "."):
                    print("Set D2 Update to True, based on time")
                    d2_update = True

        elif b[0] == "3":
            update_event = True

        elif b[0] == "4":
            #BID Driver 1
            
            
            driver_1_bid = b[2:].rstrip()
            if driver_1_bid != "" and "date" not in driver_1_bid:
                print("Updating BID for driver 1 to", driver_1_bid)

                db_handler.update_driver(D1=driver_1_bid)
                
                data_sock["Driver1"]["bid"] = driver_1_bid
                data_sock["Driver1"]["time"] = "0"
                d1_update = True
                print(driver_1_bid)

        elif b[0] == "5":
            #BID Driver 2
            
            driver_2_bid = b[2:].rstrip()
            if driver_2_bid != "":
                print("Updating BID for driver 2 to", driver_2_bid)
                db_handler.update_driver(D2=driver_2_bid)
                data_sock["Driver2"]["bid"] = driver_2_bid
                data_sock["Driver2"]["time"] = "0"
                d2_update = True

        elif b[0] == "6":
            #Driver 1, first name
            driver_1_first_name = b[2:].rstrip()
            data_sock["Driver1"]["first_name"] = driver_1_first_name
            print(driver_1_first_name)
        elif b[0] == "7":
            #Driver 1, last name
            driver_1_last_name = b[2:].rstrip()
            data_sock["Driver1"]["last_name"] = driver_1_last_name
            print(driver_1_last_name)
        elif b[0] == "8":
            #Driver 2, first name
            driver_2_first_name = b[2:].rstrip()
            data_sock["Driver2"]["first_name"] = driver_2_first_name
            print(driver_2_first_name)
        elif b[0] == "9":
            #Driver 2, last name
            driver_2_last_name = b[2:].rstrip()
            data_sock["Driver2"]["last_name"] = driver_2_last_name

            print(driver_2_last_name)
        elif b[0] == "A":
            #Driver 1, snowmobile
            driver_1_snowmobile = b[2:].rstrip()
            data_sock["Driver1"]["snowmobile"] = driver_1_snowmobile
            print(driver_1_snowmobile)
        elif b[0] == "B":
            #Driver 2, snowmobile
            driver_2_snowmobile = b[2:].rstrip()
            data_sock["Driver2"]["snowmobile"] = driver_2_snowmobile
            print(driver_2_snowmobile)
        elif b[0] == "C":
            #Update event
            update_event = True

    if d1_update == True and d2_update == True:
        update_event = True

    if update_event  == True:
        print("Updating....")

        if str(use_inter) != "1" or old_main_driver != data_sock["Driver1"]["bid"]:
            asyncio.create_task(async_update_event(listen_ip))
            old_main_driver = data_sock["Driver1"]["bid"]


        d1_update = False
        d2_update = False
        update_event = False
        

    #if len(data_sock["Driver1"]["time"]) > 3 and len(data_sock["Driver1"]["time"]) > 3:
    #    upate
    #    asyncio.create_task(async_update_event(listen_ip))

    #if update_field == True:
    #    await async_update_event(listen_ip)
    #    update_field = False

async def server(ws, path):
    while True:
        await asyncio.sleep(0.1)
        if ws.open:
            try:
                message_to_send = json.dumps(data_sock, indent=4)
                await ws.send(message_to_send)
                # Check and act on update_field
            except Exception as e:
                logging.error(f"WebSocket error: {e}")
                break
        else:
            logging.info("WebSocket connection is closed. Stopping message send.")
            break



async def handle_client(reader, writer):
    db_handler = DatabaseHandler(DB_PATH)
    try:
        while True:
            data = await reader.read(2048)
            if data:

                await data_clean(data, db_handler)
            await asyncio.sleep(0.1)
    finally:
        del db_handler

async def main():
    server = await asyncio.start_server(handle_client, listen_ip, 7000)

    async with server:
        await server.serve_forever()

async def start_servers():
    await asyncio.gather(websockets.serve(server, '0.0.0.0', 4444), main())

if __name__ == '__main__':
    asyncio.run(start_servers())
