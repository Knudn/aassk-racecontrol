# python 3.11

import random

import paho.mqtt.client as mqtt_client
import json
import os

import sqlite3

current_working_directory = os.getcwd()

DB_PATH = f"{current_working_directory}/site.db"
with sqlite3.connect(DB_PATH) as con:
    cur = con.cursor()
    starter_config = cur.execute("SELECT * FROM start_logic;").fetchone()

req_field_ready = bool(starter_config[12])
req_mon_ready = bool(starter_config[13])
field_can_start = bool(starter_config[14])
mon_can_start = bool(starter_config[15])
sl_use_warmup_image = bool(starter_config[16])
print(sl_use_warmup_image)

broker = "127.0.0.1"
port = 1883
topic = "start/#"
client_id = "MQTT_CONTROLLER"

current_state = {}

def connect_mqtt() -> mqtt_client:
    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            print("Connected to MQTT Broker!")
        else:
            print("Failed to connect, return code %d\n", rc)

    client = mqtt_client.Client(mqtt_client.CallbackAPIVersion.VERSION1, client_id)
    client.on_connect = on_connect
    client.connect(broker, port)
    return client


def publish(client, msg, topic_dev):
    result = client.publish(topic_dev, msg, retain=True)
    status = result[0]
    if status == 0:
        print(f"Send `{msg}` to topic `{topic_dev}`")
    else:
        print(f"Failed to send message to topic {topic_dev}")

def subscribe(client: mqtt_client):
    global current_state

    def on_message(client, userdata, msg):
        global current_state
        global req_field_ready
        global req_mon_ready
        global field_can_start
        global mon_can_start

        topic = msg.topic
        msg = str(msg.payload.decode("utf-8", "ignore"))
        msg_dict = json.loads(msg)

        if topic == "start/state":
            current_state = msg_dict

        elif topic == "start/starter_cr":
            if msg_dict["action"] == "halt":
                if msg_dict["value"] == True:
                    current_state["halt_race"] = True
                else:
                    current_state["halt_race"] = False
            elif msg_dict["action"] == "ready" and req_mon_ready:
                if current_state["man_ready"] == True:
                    if req_field_ready == False:
                        current_state["ready"] = False
                    current_state["man_ready"] = False
                else:
                    if req_field_ready == False:
                        current_state["ready"] = True
                    current_state["man_ready"] = True
                
                current_state["started"]

            elif msg_dict["action"] == "start":

                if mon_can_start and current_state["ready"] and current_state["man_ready"] and current_state["started"] != True:
                    current_state["started"] = True
                    current_state["man_ready"] = False
                    current_state["ready"] = False
                    if sl_use_warmup_image:
                        current_state["warmup"] = True
                    else:
                        current_state["warmup"] = False
                else:
                    current_state["started"] = False
 
            publish(client, json.dumps(current_state), "start/state")
        elif topic == "start/starter_field":
            if current_state["halt_race"] == True:
                pass
            elif msg_dict["action"] == "ready" and req_field_ready:
                if current_state["ready"] == True:
                    if req_mon_ready == False:
                        current_state["man_ready"] = False
                    current_state["ready"] = False
                else:
                    if req_mon_ready == False:
                        current_state["man_ready"] = True
                    current_state["ready"] = True
                current_state["started"] = False
            elif msg_dict["action"] == "start":

                if field_can_start and current_state["man_ready"] and current_state["ready"] and current_state["started"] != True:
                    current_state["started"] = True
                    current_state["man_ready"] = False
                    current_state["ready"] = False
                    
                    if sl_use_warmup_image:
                        current_state["warmup"] = True
                    else:
                        current_state["warmup"] = False
                
                else:
                    current_state["started"] = False
                    


            publish(client, json.dumps(current_state), "start/state")
        

    client.subscribe(topic)
    client.on_message = on_message


def run():
    import time
    global current_state

    client = connect_mqtt()
    subscribe(client)
    client.loop_forever()


if __name__ == "__main__":
    run()
