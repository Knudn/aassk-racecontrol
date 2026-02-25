import asyncio
import websockets
import csv
import json
import logging
import io
import os
import urllib.request
from websockets.exceptions import ConnectionClosed
from logging.handlers import RotatingFileHandler


# ── Logging ──────────────────────────────────────────────────────────────────
_log_dir = os.path.join(os.getcwd(), 'logs')
os.makedirs(_log_dir, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
    handlers=[
        RotatingFileHandler(
            os.path.join(_log_dir, 'orbits_display_proxy.log'),
            maxBytes=10_000_000, backupCount=5
        ),
        logging.StreamHandler()
    ]
)

current_working_directory = os.getcwd()
logging.info("Working directory: %s", current_working_directory)


# ── Orbits 5 source ──────────────────────────────────────────────────────────
ORBITS_HOST = "192.168.20.23"
ORBITS_PORT = 50000

# ── WebSocket server port (same as msport_display_proxy) ────────────────────
WS_PORT = 4444

# Reconnect delay in seconds when the Orbits TCP connection drops
RECONNECT_DELAY = 5

# Race control API endpoint
RACECONTROL_API = "http://192.168.1.50:7777/api/get_event_data?active=true"


# ── Shared state broadcast to WebSocket clients ──────────────────────────────
race_state = {
    "timer": "00:00:00",
    "laps_to_go": 0,
    "status": "",
}

# Data fetched from the race control API on event change
event_state = {
    "finish_criteria": "",
    "finish_laps": 0,
    "finish_time": "",
    "heat": 0,
    "heats": 0,
    "title": "",
}

_current_event_name = None
_fetch_task = None  # type: asyncio.Task | None


# ── Helpers ──────────────────────────────────────────────────────────────────
def format_finish_time(minutes: int) -> str:
    """Convert integer minutes to MM:SS string (no hours digit)."""
    total_seconds = minutes * 60
    m = total_seconds // 60
    s = total_seconds % 60
    return f"{m:02d}:{s:02d}"


def build_output() -> dict:
    """Build the JSON payload to send to WebSocket clients."""
    laps = race_state["laps_to_go"]
    timer = race_state["timer"]
    status = race_state["status"]

    # Warmup: Orbits uses 9999 as a sentinel for "countdown/warmup, no lap count yet"
    if laps == 9999 and status == "":
        status = "warmup"

    if status != "Green" and status != "Finish":
        # Race has not started — show the planned format from the API
        if event_state["finish_laps"]:
            laps = event_state["finish_laps"]
        if event_state["finish_time"]:
            timer = event_state["finish_time"]
    elif status == "Finish":

        if event_state["finish_laps"]:
            laps = 0
        if event_state["finish_time"]:
            timer = "00:00"
    else:
        # Race running — if Orbits still reports 9999, cap to API finish laps
        if laps == 9999 and event_state["finish_laps"]:
            laps = event_state["finish_laps"]
        if len(str(timer).split(":")) == 3:
            min_v = str(timer).split(":")[1]
            sec_v = str(timer).split(":")[2]
            timer = min_v + ":" + sec_v
    return {
        "timer": timer,
        "laps_to_go": laps,
        "status": status,
        "finish_criteria": event_state["finish_criteria"],
        "finish_laps": event_state["finish_laps"],
        "finish_time": event_state["finish_time"],
        "heat": event_state["heat"],
        "heats": event_state["heats"],
        "title": event_state["title"],
    }


# ── Event data fetch ──────────────────────────────────────────────────────────
async def _do_fetch_event():
    """Wait 2 s for the backend to update, then pull active event data."""
    await asyncio.sleep(2)
    loop = asyncio.get_running_loop()
    try:
        def _get():
            with urllib.request.urlopen(RACECONTROL_API, timeout=5) as resp:
                return json.loads(resp.read())

        data = await loop.run_in_executor(None, _get)
        event_state["finish_criteria"] = data.get("FINISH_CRITERIA", "")
        event_state["finish_laps"] = data.get("FINISH_LAPS", 0)
        raw_time = data.get("FINISH_TIME", 0)
        event_state["finish_time"] = format_finish_time(raw_time)
        event_state["heat"] = data.get("HEAT", 0)
        event_state["heats"] = data.get("HEATS", 0)
        event_state["title"] = data.get("TITLE_2", "")
        logging.info("Event data fetched: %s", event_state)
    except Exception as e:
        logging.error("Failed to fetch event data: %s", e)


def schedule_event_fetch():
    """Cancel any pending fetch and schedule a fresh one."""
    global _fetch_task
    if _fetch_task and not _fetch_task.done():
        _fetch_task.cancel()
    _fetch_task = asyncio.create_task(_do_fetch_event())


# ── Line parser ───────────────────────────────────────────────────────────────
def parse_line(line: str):
    """Parse a single Orbits 5 protocol line and update state."""
    global _current_event_name
    line = line.strip()

    if line.startswith("$B"):
        # $B,<score>,"<event_name>"  — signals which event/session is active
        try:
            reader = csv.reader(io.StringIO(line))
            fields = next(reader)
            if len(fields) >= 3:
                event_name = fields[2].strip()
                if event_name != _current_event_name:
                    logging.info("Event changed: %r -> %r", _current_event_name, event_name)
                    _current_event_name = event_name
                    schedule_event_fetch()
        except Exception:
            pass
        return

    if not line.startswith("$F"):
        return

    # $F, laps_to_go, timer, time_of_day, elapsed, status
    try:
        reader = csv.reader(io.StringIO(line))
        fields = next(reader)
    except Exception:
        return

    if len(fields) < 6:
        return

    try:
        laps_to_go = int(fields[1])
    except ValueError:
        laps_to_go = 0

    timer = fields[2].strip()
    status = fields[5].strip()

    race_state["timer"] = timer
    race_state["laps_to_go"] = laps_to_go
    race_state["status"] = status

    logging.debug("State updated: timer=%s laps_to_go=%s status=%s",
                  timer, laps_to_go, status)


# ── TCP client — connects to Orbits 5 and reads lines ────────────────────────
async def orbits_client():
    """Persistent TCP client. Reconnects automatically on disconnect."""
    buf = ""
    while True:
        logging.info("Connecting to Orbits 5 at %s:%s …", ORBITS_HOST, ORBITS_PORT)
        try:
            reader, writer = await asyncio.open_connection(ORBITS_HOST, ORBITS_PORT)
            logging.info("Connected to Orbits 5.")
            try:
                while True:
                    chunk = await reader.read(4096)
                    if not chunk:
                        logging.warning("Orbits 5 closed the connection.")
                        break
                    buf += chunk.decode('iso-8859-1', errors='replace')
                    # Process all complete lines
                    while '\n' in buf:
                        line, buf = buf.split('\n', 1)
                        parse_line(line)
            finally:
                writer.close()
        except (ConnectionRefusedError, OSError) as e:
            logging.error("Could not connect to Orbits 5: %s", e)
        except Exception as e:
            logging.error("Unexpected error in Orbits client: %s", e)

        logging.info("Reconnecting in %s s …", RECONNECT_DELAY)
        await asyncio.sleep(RECONNECT_DELAY)


# ── WebSocket server — streams race_state to every connected client ───────────
async def ws_handler(websocket, path=None):
    logging.info("WebSocket client connected: %s", websocket.remote_address)
    try:
        while True:
            try:
                await websocket.send(json.dumps(build_output()))
                await asyncio.sleep(0.1)
            except ConnectionClosed:
                logging.info("WebSocket client disconnected.")
                break
            except Exception as e:
                logging.error("WebSocket send error: %s", e)
                break
    except Exception as e:
        logging.error("Error in ws_handler: %s", e)


async def start_servers():
    ws_server = websockets.serve(ws_handler, '0.0.0.0', WS_PORT)
    async with ws_server:
        logging.info("WebSocket server listening on port %s", WS_PORT)
        await orbits_client()          # blocks; reconnects forever


if __name__ == '__main__':
    asyncio.run(start_servers())
