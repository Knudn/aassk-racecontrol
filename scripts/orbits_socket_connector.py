#!/usr/bin/env python3
import socket, threading, time, json, requests
import socketio
import paho.mqtt.client as mqtt
import logging
import os
from logging.handlers import RotatingFileHandler

_log_dir = os.path.join(os.getcwd(), 'logs')
os.makedirs(_log_dir, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
    handlers=[
        RotatingFileHandler(os.path.join(_log_dir, 'orbits_socket_connector.log'), maxBytes=10_000_000, backupCount=5),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

state = {
    "finish_criteria": "", "finish_laps": 0, "finish_time": 0,
    "finished": False, "event_checksum": "",
    "time_to_go": "0", "laps_to_go": "0",
    "warmup": False, "running": False, "halt": False,
}
lock = threading.Lock()

sio_in  = socketio.Client()
mqtt_out = mqtt.Client()
mqtt_in  = mqtt.Client(client_id="orbits_in")
old_msg = ""
def clean(s):
    return s.replace('"', '').strip()

def fetch_event_data():
    try:
        r = requests.get("http://192.168.1.50:7777/api/get_event_data?active=true", timeout=3)
        data = r.json()
        with lock:
            state["finish_criteria"] = data.get("FINISH_CRITERIA", "")
            state["finish_laps"]     = data.get("FINISH_LAPS", 0)
            state["finish_time"]     = data.get("FINISH_TIME", 0)
            state["event_checksum"]  = data.get("EVENT_CHECKSUM", "")
        logger.info("[HTTP] criteria=%s laps=%s time=%s", state['finish_criteria'], state['finish_laps'], state['finish_time'])
    except Exception as e:
        logger.error("[HTTP] failed: %s", e)

def panel(source):
    global old_msg
    with lock:
        s = dict(state)

    logger.info("[%s] warmup=%s running=%s finished=%s halt=%s", source, s['warmup'], s['running'], s['finished'], s['halt'])

    if s["halt"]:
        payload = {"text": "HALT", "color": "#FF0000", "font_size": 60}
    elif s["finished"]:
        payload = {"image_preset": "checkered_flag"}
    elif s["warmup"]:
        criteria = s["finish_criteria"]
        if criteria == "time_plus_rounds":
            finish_time = str(s["finish_time"]).zfill(2) + ":" + "00" 

            s['finish_laps'] = "R: " + str(s['finish_laps'])
            payload = {"text": f"{finish_time}\n{s['finish_laps']}", "color": "#FFAA00", "font_size": 45}
        elif criteria == "time":
            minutes = s['finish_time']
            s['finish_time'] = f"{minutes//60:02d}:{minutes%60:02d}:00"
            payload = {"text": f"{s['finish_time']}", "color": "#FFAA00", "font_size": 60}
        elif criteria in ("laps", "individual_laps"):
            payload = {"text": f"{s['finish_laps']}", "color": "#FFAA00", "font_size": 60}
        else:
            payload = {"text": "Waiting...", "color": "#FFAA00", "font_size": 40}
    elif s["running"]:
        criteria = s["finish_criteria"]
        if criteria == "time_plus_rounds":
            time_val = s["time_to_go"] if str(s["time_to_go"]) not in ("0", "00:00:00") else ""
            logger.debug("time_val: %s", time_val)
            if len(time_val.split(":")) == 3:
                min = time_val.split(":")[1]
                sec = time_val.split(":")[2]
                time_val = f"{min}:{sec}"

            laps_val = s["laps_to_go"] if str(s["laps_to_go"]) not in ("0", "9999") else s["finish_laps"]
            laps_val = f"LAPS: {laps_val}"
            
            payload = {"text": f"{time_val}\n{laps_val}", "color": "#FFFFFF", "font_size": 45}
        elif criteria == "time":
            payload = {"text": f"{s['time_to_go']}", "color": "#00FF00", "font_size": 60}
        elif criteria in ("laps", "individual_laps"):
            payload = {"text": f"{s['laps_to_go']}", "color": "#00FF00", "font_size": 60}
        else:
            return
    else:
        return

    msg = json.dumps(payload)
    logger.debug("Panel payload: %s", msg)
    if msg != old_msg:
        old_msg = msg
        mqtt_out.publish("orbits/display", msg)


def tcp_thread():
    while True:
        try:
            sock = socket.socket()
            sock.connect(('192.168.20.23', 50000))
            logger.info("[TCP] Connected")
            buf = ""
            while True:
                chunk = sock.recv(1024).decode('latin-1')
                if not chunk:
                    break
                buf += chunk
                *lines, buf = buf.split("\n")
                for line in lines:
                    parts = line.strip().split(",")
                    tag = clean(parts[0])
                    if tag == "$F" and len(parts) >= 3:
                        with lock:
                            state["laps_to_go"] = clean(parts[1])
                            state["time_to_go"]  = clean(parts[2])
                            no_criteria = not state["finish_criteria"]
                        if no_criteria:
                            fetch_event_data()
                        panel("TCP $F")
        except socket.error as e:
            logger.warning("[TCP] %s — retry in 5s", e)
        finally:
            sock.close()
        time.sleep(5)

def ws_thread():
    @sio_in.event
    def connect():
        logger.info("[WS] Connected")
        sio_in.emit("join", {"room": "default", "user": "D1"})

    @sio_in.on("response")
    def on_response(raw):
        data = json.loads(raw) if isinstance(raw, str) else raw
        if "FINISH_CRITERIA" not in data:
            return
        with lock:
            state["event_checksum"]  = data.get("EVENT_CHECKSUM", "")
            state["finished"]        = data.get("FINISHED", False)
            state["finish_criteria"] = data.get("FINISH_CRITERIA", "")
            state["finish_laps"]     = data.get("FINISH_LAPS", 0)
            state["finish_time"]     = data.get("FINISH_TIME", 0)
        panel("WS")

    while True:
        try:
            sio_in.connect("http://192.168.1.50:7777")
            sio_in.wait()
        except Exception as e:
            logger.warning("[WS] %s — retry in 5s", e)
        time.sleep(5)

def mqtt_thread():
    def on_connect(client, userdata, flags, rc):
        logger.info("[MQTT IN] Connected rc=%s", rc)
        client.subscribe("start/state")

    def on_message(client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode())
            logger.info("[MQTT IN] %s", data)
            with lock:
                state["warmup"]   = data.get("orbits_warmup", False)
                state["finished"] = data.get("orbits_finish", False)
                state["running"]  = data.get("running", False)
                state["halt"]     = data.get("halt_race", False)
                no_criteria = not state["finish_criteria"]
            if no_criteria:
                fetch_event_data()
            panel("MQTT")
        except Exception as e:
            logger.error("[MQTT IN] parse error: %s", e)

    mqtt_in.on_connect = on_connect
    mqtt_in.on_message = on_message
    while True:
        try:
            mqtt_in.connect("192.168.1.50", 1883, 60)
            mqtt_in.loop_forever()
        except Exception as e:
            logger.warning("[MQTT IN] %s — retry in 5s", e)
        time.sleep(5)

def connect_mqtt_out():
    while True:
        try:
            mqtt_out.connect("192.168.1.50", 1883, 60)
            mqtt_out.loop_start()
            logger.info("[MQTT OUT] Connected")
            break
        except Exception as e:
            logger.warning("[MQTT OUT] %s — retry in 5s", e)
        time.sleep(5)

if __name__ == "__main__":
    connect_mqtt_out()
    threading.Thread(target=ws_thread,   daemon=True).start()
    threading.Thread(target=tcp_thread,  daemon=True).start()
    threading.Thread(target=mqtt_thread, daemon=True).start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
