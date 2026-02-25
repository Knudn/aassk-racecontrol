#!/usr/bin/env python3
"""
FPP LED Panel Display Service — Mode-Based Architecture

Modes:
  - off:            Clear display, no active rendering
  - clock:          Renders HH:MM:SS via FPP text API every second
  - mqtt_subscribe: Subscribes to a user-specified MQTT topic, displays text/image presets via FPP API

Start/State Flag System:
  When flag_enabled is True, subscribes to MQTT start/state topic.
  On message: parses JSON, walks flag_priorities, fills panel with first active flag's color.
  Overrides mode rendering while any flag is active.
"""
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime
from threading import Thread, Event, Timer, Lock

import netifaces
import paho.mqtt.client as mqtt
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR = '/home/fpp/logs'
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(LOG_DIR, 'display_service.log'))
    ]
)
logger = logging.getLogger('display_service')

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CONFIG_FILE = '/home/fpp/config/display_config.json'
FPP_API_BASE = 'http://localhost/api'
SHM_OVERLAY = '/dev/shm/FPP-Model-Overlay-Buffer-LED Panels'
SHM_DATA = '/dev/shm/FPP-Model-Data-LED Panels'

DEFAULT_CONFIG = {
    'active_mode': 'off',
    'mqtt_broker': '192.168.1.50',
    'mqtt_port': 1883,
    'mqtt_keepalive': 30,
    'mqtt_reconnect_delay': 5,
    'mqtt_subscribe_topic': '',
    'mode_font_size': 60,
    'flag_enabled': False,
    'flag_colors': {
        "halt_race": "#FF0000", "warmup": "#FFAA00", "running": "#00FF00",
        "ready": "#00FF00", "started": "#FFFFFF", "orbits_finish": "#FFFFFF",
        "orbits_warmup": "#FFAA00", "man_ready": "#0000FF"
    },
    'flag_fields_enabled': {
        "halt_race": True, "warmup": True, "running": True,
        "ready": True, "started": True, "orbits_finish": True,
        "orbits_warmup": True, "man_ready": True
    },
    'flag_priorities': [
        "halt_race", "orbits_finish", "running", "warmup",
        "orbits_warmup", "started", "ready", "man_ready"
    ],
    'brightness': 100,
}

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
app = Flask(__name__)
CORS(app)

stop_event = Event()

state = {
    'active_mode': 'off',
    'clock_thread': None,
    'flag_override_active': False,
    'last_flag_color': None,
}

mqtt_state = {
    'client': None,
    'connected': False,
    'reconnect_timer': None,
    'watchdog_timer': None,
    'subscribed_topics': set(),
}

config_lock = Lock()

# ---------------------------------------------------------------------------
# Configuration management
# ---------------------------------------------------------------------------
def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            cfg = json.load(f)
            for key, value in DEFAULT_CONFIG.items():
                if key not in cfg:
                    cfg[key] = value
            return cfg
    except (FileNotFoundError, json.JSONDecodeError):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()


def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(cfg, f, indent=4)
        return True
    except Exception as e:
        logger.error(f"Error saving config: {e}")
        return False


# ---------------------------------------------------------------------------
# Network utilities
# ---------------------------------------------------------------------------
def get_local_ip():
    private_prefixes = ['192.168.', '172.16.', '10.']
    try:
        interfaces = netifaces.interfaces()
        for iface_priority in [['eth0'], [i for i in interfaces if i not in ('eth0', 'wlan0', 'lo')], ['wlan0']]:
            for iface in iface_priority:
                if iface in interfaces:
                    addrs = netifaces.ifaddresses(iface)
                    if netifaces.AF_INET in addrs:
                        for addr_info in addrs[netifaces.AF_INET]:
                            ip = addr_info['addr']
                            if any(ip.startswith(p) for p in private_prefixes):
                                return ip
        return "127.0.0.1"
    except Exception as e:
        logger.error(f"Error getting local IP: {e}")
        return "127.0.0.1"


# ---------------------------------------------------------------------------
# FPP LED Panel API helpers
# ---------------------------------------------------------------------------
def send_to_led_panel(text, font_size=60, color="#FFFFFF"):
    """Send text to the FPP LED panel via overlay text API."""
    if not text:
        return False
    if state['flag_override_active']:
        logger.debug(f"Flag override active, suppressing text: {text[:30]}")
        return False
    try:
        payload = {
            "Message": str(text),
            "Position": "center",
            "Font": "Helvetica",
            "FontSize": font_size,
            "AntiAlias": False,
            "PixelsPerSecond": 20,
            "Color": color,
            "AutoEnable": True,
        }
        response = requests.put(
            f"{FPP_API_BASE}/overlays/model/LED Panels/text",
            headers={'Content-Type': 'application/json'},
            data=json.dumps(payload),
            timeout=3,
        )
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Error sending to LED panel: {e}")
        return False


def enable_led_panel():
    """Ensure the LED panel overlay model is enabled in FPP."""
    try:
        headers = {'Content-Type': 'application/json'}
        response = requests.get(
            f"{FPP_API_BASE}/overlays/model/LED Panels/state",
            headers=headers, timeout=3,
        )
        if response.status_code == 200 and response.json().get("isActive") == 0:
            requests.put(
                f"{FPP_API_BASE}/overlays/model/LED Panels/state",
                headers=headers, data=json.dumps({"State": 1}), timeout=3,
            )
            logger.info("LED panel model enabled")
        return True
    except Exception as e:
        logger.error(f"Error enabling LED panel: {e}")
        return False


def get_panel_dimensions():
    """Get LED panel width and height from FPP API."""
    try:
        response = requests.get(f"{FPP_API_BASE}/overlays/models", timeout=3)
        if response.status_code == 200:
            for model in response.json():
                if model.get("Name") == "LED Panels":
                    return model.get("width", 192), model.get("height", 128)
    except Exception as e:
        logger.error(f"Error getting panel dimensions: {e}")
    return 192, 128


def clear_display():
    """Clear the LED panel overlay fully — text, fill, pixel data, and playlists."""
    # Clear overlay (text layer)
    try:
        requests.post(f"{FPP_API_BASE}/overlays/model/LED Panels/clear", timeout=3)
    except Exception:
        pass
    # Fill with black to wipe any solid color or pixel buffer content
    try:
        requests.put(
            f"{FPP_API_BASE}/overlays/model/LED%20Panels/fill",
            headers={'Content-Type': 'application/json'},
            data=json.dumps({"RGB": [0, 0, 0]}),
            timeout=3,
        )
    except Exception:
        pass
    # Disable the overlay model so the black fill doesn't block playlists
    try:
        requests.put(
            f"{FPP_API_BASE}/overlays/model/LED%20Panels/state",
            headers={'Content-Type': 'application/json'},
            data=json.dumps({"State": 0}),
            timeout=3,
        )
    except Exception:
        pass
    # Stop any running playlist
    try:
        requests.get(f"{FPP_API_BASE}/playlists/stop", timeout=3)
    except Exception:
        pass


def _write_to_shm(buf):
    """Write raw RGB buffer to FPP shared memory.

    Tries SHM_DATA first (pure pixel data, no header), then SHM_OVERLAY
    (has a 16-byte header that must be preserved/skipped).
    """
    # Try the Data file first — it's pure pixel data with no header
    try:
        fd = os.open(SHM_DATA, os.O_WRONLY)
        os.write(fd, buf)
        os.close(fd)
        logger.debug(f"Wrote {len(buf)} bytes to SHM_DATA")
        return True
    except PermissionError:
        logger.warning(f"Permission denied writing to {SHM_DATA} — try: sudo chmod 666 \"{SHM_DATA}\"")
    except Exception as e:
        logger.debug(f"SHM_DATA write failed: {e}")

    # Try the Overlay Buffer — skip the 16-byte header
    try:
        fd = os.open(SHM_OVERLAY, os.O_WRONLY)
        os.lseek(fd, 16, os.SEEK_SET)  # Skip 16-byte header
        os.write(fd, buf)
        os.close(fd)
        logger.debug(f"Wrote {len(buf)} bytes to SHM_OVERLAY (offset 16)")
        return True
    except PermissionError:
        logger.warning(f"Permission denied writing to {SHM_OVERLAY} — try: sudo chmod 666 \"{SHM_OVERLAY}\"")
    except Exception as e:
        logger.debug(f"SHM_OVERLAY write failed: {e}")

    return False


def _push_pixel_buffer(buf):
    """Push a raw RGB pixel buffer to the LED panel.

    Tries three methods in order:
    1. HTTP PUT to /api/overlays/model/.../data/raw (binary upload)
    2. Shared memory write
    3. Logs failure
    """
    # Method 1: HTTP API raw data upload
    try:
        response = requests.put(
            f"{FPP_API_BASE}/overlays/model/LED%20Panels/data/raw",
            headers={'Content-Type': 'application/octet-stream'},
            data=bytes(buf),
            timeout=5,
        )
        if response.status_code == 200:
            enable_led_panel()
            return True
        logger.debug(f"Raw data API returned {response.status_code}, trying shm")
    except Exception as e:
        logger.debug(f"Raw data API failed: {e}, trying shm")

    # Method 2: Shared memory
    if _write_to_shm(buf):
        enable_led_panel()
        return True

    logger.warning("Could not push pixel buffer via API or shared memory")
    return False


def send_checkered_flag(square_size=16):
    """Display a checkered flag pattern on the LED panel."""
    try:
        width, height = get_panel_dimensions()
        white = bytes([255, 255, 255])
        black = bytes([0, 0, 0])
        buf = bytearray(width * height * 3)

        for y in range(height):
            sq_y = y // square_size
            for x in range(width):
                sq_x = x // square_size
                offset = (y * width + x) * 3
                buf[offset:offset + 3] = white if (sq_x + sq_y) % 2 == 0 else black

        if _push_pixel_buffer(buf):
            logger.info("Checkered flag displayed")
            return True

        logger.warning("Checkered flag: pixel buffer push failed, falling back to text")
        send_to_led_panel("FINISH", font_size=60, color="#FFFFFF")
        return False
    except Exception as e:
        logger.error(f"Error sending checkered flag: {e}")
        return False


def _hex_to_rgb(hex_color):
    """Convert '#RRGGBB' to (r, g, b) tuple."""
    h = hex_color.lstrip('#')
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _render_stripes_horizontal(width, height, rgb1, rgb2, stripe_h=16):
    """Draw horizontal stripes via pixel buffer."""
    buf = bytearray(width * height * 3)
    c1 = bytes(rgb1)
    c2 = bytes(rgb2)
    for y in range(height):
        color = c1 if (y // stripe_h) % 2 == 0 else c2
        for x in range(width):
            offset = (y * width + x) * 3
            buf[offset:offset + 3] = color
    _push_pixel_buffer(buf)


def _render_diagonal_stripes(width, height, rgb1, rgb2, stripe_w=20):
    """Draw diagonal stripes via pixel buffer."""
    buf = bytearray(width * height * 3)
    c1 = bytes(rgb1)
    c2 = bytes(rgb2)
    for y in range(height):
        for x in range(width):
            color = c1 if ((x + y) // stripe_w) % 2 == 0 else c2
            offset = (y * width + x) * 3
            buf[offset:offset + 3] = color
    _push_pixel_buffer(buf)


def _render_cross(width, height, bg_rgb, fg_rgb, thickness=8):
    """Draw an X cross pattern via pixel buffer."""
    buf = bytearray(width * height * 3)
    bg = bytes(bg_rgb)
    fg = bytes(fg_rgb)
    half_t = thickness // 2

    for y in range(height):
        cx1 = int(y * width / height)
        cx2 = int((height - 1 - y) * width / height)
        for x in range(width):
            on_diag1 = abs(x - cx1) <= half_t
            on_diag2 = abs(x - cx2) <= half_t
            color = fg if (on_diag1 or on_diag2) else bg
            offset = (y * width + x) * 3
            buf[offset:offset + 3] = color
    _push_pixel_buffer(buf)


# Registry of available image presets
IMAGE_PRESETS = {
    'checkered_flag': 'Classic checkered flag (black & white)',
    'solid_red': 'Solid red fill',
    'solid_green': 'Solid green fill',
    'solid_blue': 'Solid blue fill',
    'solid_yellow': 'Solid yellow fill',
    'stripes_red_white': 'Horizontal red & white stripes',
    'stripes_yellow_black': 'Horizontal yellow & black caution stripes',
    'diagonal_red_white': 'Diagonal red & white stripes',
    'cross_red': 'Red X on black background',
}


def render_image_preset(preset_name, color=None):
    """Render a named image preset to the LED panel using the FPP fill API.

    Args:
        preset_name: One of the keys in IMAGE_PRESETS.
        color: Optional hex color override for solid_* presets (e.g. '#FF00FF').

    Returns:
        True on success, False otherwise.
    """
    try:
        width, height = get_panel_dimensions()
        enable_led_panel()

        if preset_name == 'checkered_flag':
            return send_checkered_flag()

        elif preset_name.startswith('solid_'):
            solid_colors = {
                'solid_red': '#FF0000',
                'solid_green': '#00FF00',
                'solid_blue': '#0000FF',
                'solid_yellow': '#FFFF00',
            }
            hex_c = color or solid_colors.get(preset_name, '#FFFFFF')
            return fill_solid_color(hex_c)

        elif preset_name == 'stripes_red_white':
            _render_stripes_horizontal(width, height, (255, 0, 0), (255, 255, 255))

        elif preset_name == 'stripes_yellow_black':
            _render_stripes_horizontal(width, height, (255, 255, 0), (0, 0, 0), stripe_h=12)

        elif preset_name == 'diagonal_red_white':
            _render_diagonal_stripes(width, height, (255, 0, 0), (255, 255, 255))

        elif preset_name == 'cross_red':
            _render_cross(width, height, (0, 0, 0), (255, 0, 0))

        else:
            logger.warning(f"Unknown image preset: {preset_name}")
            return False

        logger.info(f"Rendered image preset: {preset_name}")
        return True

    except Exception as e:
        logger.error(f"Error rendering image preset '{preset_name}': {e}")
        return False


def fill_solid_color(hex_color):
    """Fill the entire LED panel with a solid color using the FPP overlay fill API."""
    try:
        hex_color = hex_color.lstrip('#')
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)

        enable_led_panel()

        # Use the same PUT /fill API that the FPP matrix tools GUI uses
        response = requests.put(
            f"{FPP_API_BASE}/overlays/model/LED%20Panels/fill",
            headers={'Content-Type': 'application/json'},
            data=json.dumps({"RGB": [r, g, b]}),
            timeout=3,
        )

        if response.status_code == 200:
            logger.info(f"Filled panel with color #{hex_color} (RGB: {r},{g},{b})")
            return True
        else:
            logger.warning(f"Fill API returned status {response.status_code}: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Error filling solid color: {e}")
        return False


# ---------------------------------------------------------------------------
# Clock mode — render HH:MM:SS via FPP text overlay API every second
# ---------------------------------------------------------------------------
def _clock_loop():
    """Thread function: updates the FPP text overlay with the current time every second."""
    enable_led_panel()
    cfg = load_config()
    font_size = cfg.get('mode_font_size', 60)
    logger.info(f"Clock mode started (font_size={font_size})")

    last_text = ""
    while not stop_event.is_set():
        if state['flag_override_active']:
            last_text = ""  # Force re-render when flag clears
            time.sleep(0.5)
            continue

        now = datetime.now().strftime("%H:%M:%S")
        if now != last_text:
            try:
                payload = {
                    "Message": now,
                    "Position": "center",
                    "Font": "Helvetica",
                    "FontSize": font_size,
                    "AntiAlias": False,
                    "PixelsPerSecond": 0,
                    "Color": "#FFFFFF",
                    "AutoEnable": True,
                }
                requests.put(
                    f"{FPP_API_BASE}/overlays/model/LED Panels/text",
                    headers={'Content-Type': 'application/json'},
                    data=json.dumps(payload),
                    timeout=2,
                )
                last_text = now
            except Exception as e:
                logger.warning(f"Clock update failed: {e}")

        # Sleep until next second boundary
        time.sleep(1.0 - (time.time() % 1.0))

    logger.info("Clock mode stopped")


# ---------------------------------------------------------------------------
# Mode manager
# ---------------------------------------------------------------------------
def stop_current_mode():
    """Stop whatever mode is currently running."""
    stop_event.set()
    if state['clock_thread'] and state['clock_thread'].is_alive():
        state['clock_thread'].join(timeout=3)
    state['clock_thread'] = None
    stop_event.clear()

    # Unsubscribe from mode-specific MQTT topics
    client = mqtt_state['client']
    if client and mqtt_state['connected']:
        for topic in list(mqtt_state['subscribed_topics']):
            if topic != 'start/state':
                try:
                    client.unsubscribe(topic)
                except Exception:
                    pass
                mqtt_state['subscribed_topics'].discard(topic)

    state['active_mode'] = 'off'
    state['flag_override_active'] = False
    state['last_flag_color'] = None


def activate_mode(mode, mqtt_topic=''):
    """Activate a new display mode."""
    stop_current_mode()

    cfg = load_config()
    cfg['active_mode'] = mode
    if mqtt_topic:
        cfg['mqtt_subscribe_topic'] = mqtt_topic
    save_config(cfg)

    state['active_mode'] = mode
    enable_led_panel()

    if mode == 'off':
        clear_display()
        logger.info("Mode: off")

    elif mode == 'clock':
        clear_display()
        t = Thread(target=_clock_loop, daemon=True)
        t.start()
        state['clock_thread'] = t
        logger.info("Mode: clock")

    elif mode == 'mqtt_subscribe':
        clear_display()
        topic = mqtt_topic or cfg.get('mqtt_subscribe_topic', '')
        if topic and mqtt_state['client'] and mqtt_state['connected']:
            mqtt_state['client'].subscribe(topic)
            mqtt_state['subscribed_topics'].add(topic)
            logger.info(f"Mode: mqtt_subscribe → {topic}")
        else:
            logger.warning("mqtt_subscribe mode: no topic or MQTT not connected")

    else:
        logger.warning(f"Unknown mode: {mode}")


# ---------------------------------------------------------------------------
# Start/State Flag System
# ---------------------------------------------------------------------------
def handle_flag_message(payload_str):
    """Handle a message on start/state topic — fill panel with priority color."""
    cfg = load_config()
    if not cfg.get('flag_enabled', False):
        return

    try:
        data = json.loads(payload_str)
    except (json.JSONDecodeError, TypeError):
        logger.warning(f"Invalid JSON on start/state: {payload_str}")
        return

    priorities = cfg.get('flag_priorities', DEFAULT_CONFIG['flag_priorities'])
    colors = cfg.get('flag_colors', DEFAULT_CONFIG['flag_colors'])
    fields_enabled = cfg.get('flag_fields_enabled', DEFAULT_CONFIG['flag_fields_enabled'])

    active_color = None
    for field in priorities:
        if not fields_enabled.get(field, True):
            continue
        if data.get(field, False):
            active_color = colors.get(field)
            if active_color:
                break

    if active_color:
        if state['last_flag_color'] != active_color:
            fill_solid_color(active_color)
            state['last_flag_color'] = active_color
        state['flag_override_active'] = True
        logger.info(f"Flag active: color {active_color}")
    else:
        if state['flag_override_active']:
            state['flag_override_active'] = False
            state['last_flag_color'] = None
            logger.info("All flags cleared, resuming mode")
            # Resume the current mode display
            _resume_after_flag()


def _resume_after_flag():
    """Re-activate the current mode after flag override clears."""
    mode = state['active_mode']
    if mode == 'off':
        clear_display()
    elif mode == 'clock':
        pass  # Clock thread will resume rendering automatically
    elif mode == 'mqtt_subscribe':
        clear_display()
        enable_led_panel()


def update_flag_subscription(enabled):
    """Subscribe or unsubscribe from start/state based on flag_enabled."""
    client = mqtt_state['client']
    if not client or not mqtt_state['connected']:
        return

    if enabled:
        if 'start/state' not in mqtt_state['subscribed_topics']:
            client.subscribe('start/state')
            mqtt_state['subscribed_topics'].add('start/state')
            logger.info("Subscribed to start/state for flag system")
    else:
        if 'start/state' in mqtt_state['subscribed_topics']:
            client.unsubscribe('start/state')
            mqtt_state['subscribed_topics'].discard('start/state')
            state['flag_override_active'] = False
            state['last_flag_color'] = None
            logger.info("Unsubscribed from start/state")


# ---------------------------------------------------------------------------
# MQTT
# ---------------------------------------------------------------------------
def on_mqtt_connect(client, userdata, flags, rc):
    if rc == 0:
        logger.info("Connected to MQTT broker")
        mqtt_state['connected'] = True

        if mqtt_state['reconnect_timer']:
            mqtt_state['reconnect_timer'].cancel()
            mqtt_state['reconnect_timer'] = None

        client.publish("fpp_display/status", "online", qos=1, retain=True)

        # Re-subscribe to mode topics
        cfg = load_config()
        mode = cfg.get('active_mode', 'off')

        if mode == 'mqtt_subscribe':
            topic = cfg.get('mqtt_subscribe_topic', '')
            if topic:
                client.subscribe(topic)
                mqtt_state['subscribed_topics'].add(topic)

        # Re-subscribe to flag topic if enabled
        if cfg.get('flag_enabled', False):
            client.subscribe('start/state')
            mqtt_state['subscribed_topics'].add('start/state')
    else:
        logger.error(f"MQTT connect failed, code: {rc}")
        mqtt_state['connected'] = False
        schedule_mqtt_reconnect()


def on_mqtt_disconnect(client, userdata, rc):
    logger.warning(f"MQTT disconnected (rc={rc})")
    mqtt_state['connected'] = False
    mqtt_state['subscribed_topics'].clear()
    schedule_mqtt_reconnect()


def _handle_mqtt_subscribe_message(payload, default_font_size):
    """Handle a message on a user-subscribed MQTT topic.

    Expected JSON format — text mode:
        {"text": "Hello", "color": "#FF0000", "font_size": 40, "position": "center"}

    Expected JSON format — image preset mode:
        {"image_preset": "checkered_flag"}
        {"image_preset": "solid_red"}
        {"image_preset": "solid_red", "color": "#FF00FF"}   (override color)

    All fields except 'text' or 'image_preset' are optional.
    If the payload is not valid JSON, the raw string is displayed as text.
    """
    try:
        data = json.loads(payload)
        if isinstance(data, dict):
            # --- Image preset mode ---
            if 'image_preset' in data:
                preset = data['image_preset']
                color = data.get('color')
                render_image_preset(preset, color=color)
                return

            # --- Text mode ---
            if 'text' in data:
                text = str(data['text'])
                color = data.get('color', '#FFFFFF')
                font_size = int(data.get('font_size', default_font_size))
                position = data.get('position', 'center')

                req_payload = {
                    "Message": text,
                    "Position": position,
                    "Font": "Helvetica",
                    "FontSize": font_size,
                    "AntiAlias": False,
                    "PixelsPerSecond": 0,
                    "Color": color,
                    "AutoEnable": True,
                }
                requests.put(
                    f"{FPP_API_BASE}/overlays/model/LED Panels/text",
                    headers={'Content-Type': 'application/json'},
                    data=json.dumps(req_payload),
                    timeout=3,
                )
                return
    except (json.JSONDecodeError, TypeError, ValueError):
        pass  # Not JSON — fall through to plain text

    # Plain text fallback
    try:
        req_payload = {
            "Message": payload,
            "Position": "center",
            "Font": "Helvetica",
            "FontSize": default_font_size,
            "AntiAlias": False,
            "PixelsPerSecond": 0,
            "Color": "#FFFFFF",
            "AutoEnable": True,
        }
        requests.put(
            f"{FPP_API_BASE}/overlays/model/LED Panels/text",
            headers={'Content-Type': 'application/json'},
            data=json.dumps(req_payload),
            timeout=3,
        )
    except Exception as e:
        logger.error(f"Error displaying MQTT subscribe message: {e}")


def on_mqtt_message(client, userdata, msg):
    try:
        payload = msg.payload.decode('utf-8')
        logger.info(f"MQTT [{msg.topic}]: {payload[:100]}")

        # --- start/state flag handling ---
        if msg.topic == 'start/state':
            handle_flag_message(payload)
            return

        # --- mqtt_subscribe mode: parse JSON message ---
        if state['active_mode'] == 'mqtt_subscribe':
            cfg = load_config()
            user_topic = cfg.get('mqtt_subscribe_topic', '')
            if msg.topic == user_topic:
                if not state['flag_override_active']:
                    default_font_size = cfg.get('mode_font_size', 60)
                    _handle_mqtt_subscribe_message(payload, default_font_size)
            return

    except Exception as e:
        logger.error(f"Error processing MQTT message: {e}")


def schedule_mqtt_reconnect():
    if mqtt_state['reconnect_timer'] is not None:
        mqtt_state['reconnect_timer'].cancel()
    cfg = load_config()
    delay = cfg.get('mqtt_reconnect_delay', DEFAULT_CONFIG['mqtt_reconnect_delay'])
    logger.info(f"MQTT reconnect in {delay}s")
    mqtt_state['reconnect_timer'] = Timer(delay, connect_mqtt)
    mqtt_state['reconnect_timer'].daemon = True
    mqtt_state['reconnect_timer'].start()


def mqtt_watchdog():
    if not mqtt_state['connected'] and mqtt_state['reconnect_timer'] is None:
        logger.warning("MQTT lost, scheduling reconnect")
        schedule_mqtt_reconnect()
    if not stop_event.is_set():
        mqtt_state['watchdog_timer'] = Timer(60, mqtt_watchdog)
        mqtt_state['watchdog_timer'].daemon = True
        mqtt_state['watchdog_timer'].start()


def connect_mqtt():
    cfg = load_config()
    broker = cfg.get('mqtt_broker', DEFAULT_CONFIG['mqtt_broker'])
    port = cfg.get('mqtt_port', DEFAULT_CONFIG['mqtt_port'])
    keepalive = cfg.get('mqtt_keepalive', DEFAULT_CONFIG['mqtt_keepalive'])

    if mqtt_state['client'] is not None:
        try:
            mqtt_state['client'].disconnect()
            mqtt_state['client'].loop_stop()
        except Exception:
            pass

    client_id = f"fpp_display_{int(time.time())}"
    client = mqtt.Client(client_id=client_id, clean_session=True)
    client.on_connect = on_mqtt_connect
    client.on_disconnect = on_mqtt_disconnect
    client.on_message = on_mqtt_message
    client.will_set("fpp_display/status", "offline", qos=1, retain=True)

    try:
        logger.info(f"Connecting to MQTT {broker}:{port}")
        client.connect(broker, port, keepalive)
        client.loop_start()
        mqtt_state['client'] = client
    except Exception as e:
        logger.error(f"MQTT connect failed: {e}")
        schedule_mqtt_reconnect()


# ---------------------------------------------------------------------------
# Flask API routes
# ---------------------------------------------------------------------------
@app.route('/presets')
def api_presets():
    """List available image presets."""
    return jsonify(IMAGE_PRESETS)


@app.route('/render_preset', methods=['POST'])
def api_render_preset():
    """Render an image preset directly via API."""
    try:
        data = request.get_json() or {}
        preset = data.get('preset', '')
        color = data.get('color')
        if preset not in IMAGE_PRESETS:
            return jsonify({'status': 'error', 'message': f'Unknown preset: {preset}', 'available': list(IMAGE_PRESETS.keys())}), 400
        ok = render_image_preset(preset, color=color)
        return jsonify({'status': 'success' if ok else 'error', 'preset': preset})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/set_mode', methods=['POST'])
def api_set_mode():
    """Switch the active display mode."""
    try:
        data = request.get_json() or {}
        mode = data.get('mode', 'off')
        mqtt_topic = data.get('mqtt_topic', '')
        font_size = data.get('font_size')

        # Save font size to config if provided
        if font_size is not None:
            cfg = load_config()
            cfg['mode_font_size'] = int(font_size)
            save_config(cfg)

        activate_mode(mode, mqtt_topic)
        return jsonify({'status': 'success', 'mode': mode})
    except Exception as e:
        logger.error(f"Error setting mode: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/stop')
def api_stop():
    """Stop the current mode and clear the display."""
    try:
        stop_current_mode()
        clear_display()
        return jsonify({'status': 'success', 'message': 'Display stopped and cleared'})
    except Exception as e:
        logger.error(f"Error stopping: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/status')
def api_status():
    """Return current service status."""
    try:
        cfg = load_config()
        return jsonify({
            'active_mode': state['active_mode'],
            'flag_override_active': state['flag_override_active'],
            'mqtt_connected': mqtt_state['connected'],
            'subscribed_topics': list(mqtt_state['subscribed_topics']),
            'flag_enabled': cfg.get('flag_enabled', False),
            'brightness': cfg.get('brightness', 100),
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/update_config', methods=['POST'])
def api_update_config():
    """Update settings (flag colors, flag_enabled, mqtt_broker, etc.)."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'message': 'No data'}), 400

        cfg = load_config()
        for key in DEFAULT_CONFIG:
            if key in data:
                cfg[key] = data[key]
        save_config(cfg)

        # Handle flag subscription change
        if 'flag_enabled' in data:
            update_flag_subscription(data['flag_enabled'])

        # Handle MQTT settings change
        if any(k in data for k in ('mqtt_broker', 'mqtt_port', 'mqtt_keepalive')):
            if mqtt_state['client']:
                schedule_mqtt_reconnect()

        return jsonify({'status': 'success', 'config': cfg})
    except Exception as e:
        logger.error(f"Error updating config: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/display_message')
def api_display_message():
    """Display a custom text message on the LED panel."""
    try:
        message = request.args.get('message', '')
        if not message:
            return jsonify({'status': 'error', 'message': 'No message provided'}), 400

        size = int(request.args.get('size', '60'))
        color = request.args.get('color', '#FFFFFF')
        if not re.match(r'^#[0-9A-Fa-f]{6}$', color):
            color = '#FFFFFF'

        enable_led_panel()
        # Bypass flag override for explicit display_message calls
        payload = {
            "Message": str(message), "Position": "center", "Font": "Helvetica",
            "FontSize": size, "AntiAlias": False, "PixelsPerSecond": 20,
            "Color": color, "AutoEnable": True,
        }
        response = requests.put(
            f"{FPP_API_BASE}/overlays/model/LED Panels/text",
            headers={'Content-Type': 'application/json'},
            data=json.dumps(payload), timeout=3,
        )
        if response.status_code == 200:
            return jsonify({'status': 'success', 'message': 'Message displayed'})
        return jsonify({'status': 'error', 'message': 'FPP API error'}), 500
    except Exception as e:
        logger.error(f"Error displaying message: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/set_brightness', methods=['POST'])
def api_set_brightness():
    """Set FPP display brightness (0-100)."""
    try:
        data = request.get_json() or {}
        brightness = int(data.get('brightness', 100))
        brightness = max(0, min(100, brightness))

        cfg = load_config()
        cfg['brightness'] = brightness
        save_config(cfg)

        # Set brightness via FPP API
        try:
            requests.post(
                f"{FPP_API_BASE}/command",
                headers={'Content-Type': 'application/json'},
                data=json.dumps({
                    "command": "Set Channel Output Testing",
                    "args": []
                }),
                timeout=3,
            )
            # FPP uses /api/settings/brightness
            requests.put(
                "http://localhost/api/settings/brightness",
                headers={'Content-Type': 'application/json'},
                data=json.dumps({"value": brightness}),
                timeout=3,
            )
        except Exception as e:
            logger.warning(f"Could not set FPP brightness: {e}")

        return jsonify({'status': 'success', 'brightness': brightness})
    except Exception as e:
        logger.error(f"Error setting brightness: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/restart_service')
def api_restart_service():
    """Restart the FPPD service."""
    try:
        subprocess.Popen(['sudo', 'systemctl', 'restart', 'fppd'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return jsonify({'status': 'success', 'message': 'FPPD restart initiated'})
    except Exception as e:
        logger.error(f"Error restarting FPPD: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ---------------------------------------------------------------------------
# Cleanup and signal handling
# ---------------------------------------------------------------------------
def cleanup():
    logger.info("Cleaning up")
    stop_current_mode()
    if mqtt_state['client']:
        try:
            mqtt_state['client'].publish("fpp_display/status", "offline", qos=1, retain=True)
            mqtt_state['client'].disconnect()
            mqtt_state['client'].loop_stop()
        except Exception:
            pass
    for timer_key in ('reconnect_timer', 'watchdog_timer'):
        t = mqtt_state.get(timer_key)
        if t:
            t.cancel()
    logger.info("Shutdown complete")


def signal_handler(sig, frame):
    logger.info(f"Signal {sig} received, shutting down")
    cleanup()
    sys.exit(0)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)

        # Connect to MQTT
        connect_mqtt()
        mqtt_watchdog()

        # Enable panel and show startup message
        enable_led_panel()
        ip = get_local_ip()
        cfg = load_config()

        send_to_led_panel(f"Display Panel\n{ip}", font_size=30)
        logger.info(f"FPP Display Service started at {ip}")

        # Restore last active mode
        saved_mode = cfg.get('active_mode', 'off')
        if saved_mode != 'off':
            time.sleep(2)  # Give MQTT time to connect
            activate_mode(saved_mode, cfg.get('mqtt_subscribe_topic', ''))

        # Subscribe to start/state if flag is enabled
        if cfg.get('flag_enabled', False):
            # Will be handled in on_mqtt_connect after connection
            pass

        # Start Flask server
        logger.info("Starting Flask server on port 5000")
        app.run(host='0.0.0.0', port=5000, threaded=True)

    except Exception as e:
        logger.error(f"Startup error: {e}")
        cleanup()
        sys.exit(1)


if __name__ == "__main__":
    main()
