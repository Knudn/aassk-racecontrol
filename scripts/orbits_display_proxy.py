import asyncio
import websockets
import csv
import json
import logging
import io
import os
import sqlite3
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

# ── Race type ─────────────────────────────────────────────────────────────────
with sqlite3.connect("site.db") as _con:
    _cur = _con.cursor()
    RACE_TYPE = int(_cur.execute("SELECT race_type FROM global_config;").fetchone()[0])

logging.info("Race type: %s", RACE_TYPE)

# ── Orbits 5 source ──────────────────────────────────────────────────────────
ORBITS_HOST = "192.168.1.163"
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

# Parsed live from Orbits stream
competitor_state = {}   # bib -> {"firstname": str, "lastname": str}
standings_state = {}    # bib -> {"pos": int, "bib": str, "finished": bool, "time": str}
class_state = {}        # class_id -> class_name
event_info_state = {}   # e.g. {"TRACKNAME": "...", "TRACKLENGTH": "..."}

_current_event_name = None
_fetch_task = None  # type: asyncio.Task | None


# ── Helpers ──────────────────────────────────────────────────────────────────
def format_finish_time(minutes: int) -> str:
    """Convert integer minutes to MM:SS string (no hours digit)."""
    total_seconds = minutes * 60
    m = total_seconds // 60
    s = total_seconds % 60
    return f"{m:02d}:{s:02d}"


def build_standings() -> list:
    """Return standings sorted by position, with competitor names resolved."""
    result = []
    for entry in sorted(standings_state.values(), key=lambda x: x["pos"]):
        bib = entry["bib"]
        comp = competitor_state.get(bib, {})
        firstname = comp.get("firstname", "")
        lastname = comp.get("lastname", "")
        name = f"{firstname} {lastname}".strip()
        result.append({
            "pos": entry["pos"],
            "bib": bib,
            "name": name,
            "firstname": firstname,
            "lastname": lastname,
            "finished": entry["finished"],
            "time": entry["time"],
        })
    return result


def build_output() -> dict:
    """Build the JSON payload to send to WebSocket clients."""
    laps = race_state["laps_to_go"]
    timer = race_state["timer"]
    status = race_state["status"]

    # Common extra fields included regardless of race type
    extra = {
        "standings": build_standings(),
        "event_name": _current_event_name or "",
        "track_name": event_info_state.get("TRACKNAME", ""),
        "track_length": event_info_state.get("TRACKLENGTH", ""),
        "class_name": next(iter(class_state.values()), "") if class_state else "",
    }

    if RACE_TYPE == 1:
        # Bakkecross: just report elapsed time and status, nothing else needed
        if status == "":
            laps_val = int(laps) if isinstance(laps, (int, str)) and str(laps).isdigit() else 0
            if laps_val == 9999:
                status = "warmup"
        # Convert HH:MM:SS → M:SS (drop the hours field)
        parts = str(timer).split(":")
        if len(parts) == 3:
            minutes = int(parts[0]) * 60 + int(parts[1])
            timer = f"{minutes}:{parts[2]}"
        return {"timer": timer, "status": status, **extra}

    # ── All other race types: full logic ─────────────────────────────────────
    tmp_status = status
    if laps == 9999 and status == "":
        status = "warmup"
    elif status == "":
        tmp_status = True

    if status != "Green" and status != "Finish":
        if event_state["finish_laps"]:
            laps = event_state["finish_laps"]
        if event_state["finish_time"]:
            timer = event_state["finish_time"]
    elif status == "Finish":
        if event_state["finish_laps"]:
            laps = 0
        if event_state["finish_time"]:
            timer = "00:00"
    if tmp_status == True:
        timer = "00:00"
        laps = 0
    else:
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
        **extra,
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
def _csv_fields(line: str):
    """Parse a CSV line and return fields list, or None on error."""
    try:
        return next(csv.reader(io.StringIO(line)))
    except Exception:
        return None


def parse_line(line: str):
    """Parse a single Orbits 5 protocol line and update state."""
    global _current_event_name
    line = line.strip()
    if not line:
        return

    tag = line.split(",", 1)[0]

    # ── $B — event/session name ───────────────────────────────────────────────
    if tag == "$B":
        fields = _csv_fields(line)
        if fields and len(fields) >= 3:
            event_name = fields[2].strip()
            if event_name != _current_event_name:
                logging.info("Event changed: %r -> %r", _current_event_name, event_name)
                _current_event_name = event_name
                # Clear live per-session state on event change
                standings_state.clear()
                competitor_state.clear()
                class_state.clear()
                schedule_event_fetch()
        return

    # ── $F — race clock / status ──────────────────────────────────────────────
    if tag == "$F":
        # $F,<laps_to_go>,"<timer>","<time_of_day>","<elapsed>","<status>"
        fields = _csv_fields(line)
        if not fields or len(fields) < 6:
            return
        try:
            laps_to_go = int(fields[1])
        except ValueError:
            laps_to_go = 0
        status = fields[5].strip()
        timer = fields[4].strip() if RACE_TYPE == 1 else fields[2].strip()
        race_state["timer"] = timer
        race_state["laps_to_go"] = laps_to_go
        race_state["status"] = status
        logging.debug("State updated: timer=%s laps_to_go=%s status=%s",
                      timer, laps_to_go, status)
        return

    # ── $SR / $SP — standings (split result / split position) ─────────────────
    # $SR,<pos>,"<bib>",<finished>,"<time>",<transponder>
    # finished field is "1" if done, empty string if still racing
    if tag in ("$SR", "$SP"):
        fields = _csv_fields(line)
        if not fields or len(fields) < 5:
            return
        try:
            pos = int(fields[1])
        except ValueError:
            return
        bib = fields[2].strip()
        finished_raw = fields[3].strip()
        finished = finished_raw == "1"
        time_str = fields[4].strip()
        standings_state[bib] = {
            "pos": pos,
            "bib": bib,
            "finished": finished,
            "time": time_str,
        }
        return

    # ── $A — athlete / transponder entry ──────────────────────────────────────
    # $A,"<bib>","<bib2>",<transponder>,"<firstname>","<lastname>","",<flag>
    if tag == "$A":
        fields = _csv_fields(line)
        if not fields or len(fields) < 6:
            return
        bib = fields[1].strip()
        firstname = fields[4].strip()
        lastname = fields[5].strip()
        if bib not in competitor_state:
            competitor_state[bib] = {"firstname": firstname, "lastname": lastname}
        return

    # ── $COMP — competitor entry ───────────────────────────────────────────────
    # $COMP,"<bib>","<bib2>",<flag>,"<firstname>","<lastname>","",""
    if tag == "$COMP":
        fields = _csv_fields(line)
        if not fields or len(fields) < 6:
            return
        bib = fields[1].strip()
        firstname = fields[4].strip()
        lastname = fields[5].strip()
        competitor_state[bib] = {"firstname": firstname, "lastname": lastname}
        return

    # ── $C — class ────────────────────────────────────────────────────────────
    # $C,<id>,"<name>"
    if tag == "$C":
        fields = _csv_fields(line)
        if not fields or len(fields) < 3:
            return
        try:
            class_id = int(fields[1])
        except ValueError:
            class_id = fields[1]
        class_state[class_id] = fields[2].strip()
        return

    # ── $E — event / track info ───────────────────────────────────────────────
    # $E,"<KEY>","<VALUE>"
    if tag == "$E":
        fields = _csv_fields(line)
        if not fields or len(fields) < 3:
            return
        event_info_state[fields[1].strip()] = fields[2].strip()
        return


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
    last_sent = None
    try:
        while True:
            try:
                payload = json.dumps(build_output(), separators=(',', ':'))
                if payload != last_sent:
                    await websocket.send(payload)
                    last_sent = payload
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
