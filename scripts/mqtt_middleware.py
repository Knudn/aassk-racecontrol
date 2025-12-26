# python 3.11

import random

import paho.mqtt.client as mqtt_client
import json

broker = "127.0.0.1"
port = 1883
topic = "start/#"
client_id = "MQTT_CONTROLLER"

req_mon_ready = False
req_field_ready = True

mon_can_start = True
field_can_start = True

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

        topic = msg.topic
        msg = str(msg.payload.decode("utf-8", "ignore"))
        msg_dict = json.loads(msg)
        
        if topic == "start/state":
            current_state = msg_dict

        elif topic == "start/starter_field":
            if msg_dict["action"] == "ready":
                if current_state["ready"] == True:
                    if req_mon_ready == False:
                        current_state["man_ready"] = False
                    current_state["ready"] = False
                else:
                    if req_mon_ready == False:
                        current_state["man_ready"] = True
                    current_state["ready"] = True
            elif msg_dict["action"] == "start":

                mon_can_start = True
                field_can_start = True

                if field_can_start and current_state["man_ready"] and current_state["ready"]:
                    current_state["started"] = True
                    current_state["man_ready"] = False
                    current_state["ready"] = False


            publish(client, json.dumps(current_state), "start/state")
        
        print(f"Received `{msg}` from `{topic}` topic")

    client.subscribe(topic)
    client.on_message = on_message


def run():
    global current_state

    client = connect_mqtt()
    subscribe(client)
    client.loop_forever()


if __name__ == "__main__":
    run()
