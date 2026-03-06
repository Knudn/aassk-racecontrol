#!/usr/bin/env python3
"""
MSport DB Monitor
Watches Online.scdb for current event/heat changes, then monitors
the corresponding EventXXXEx.scdb for startlist and timing updates.
All DB access on the scdb files is read-only to avoid write locks.

When the next driver changes, D1 in active_drivers (site.db) is updated.
When a driver crosses the finish line, update_event is called.
"""

import sqlite3
import time
import os
import sys
import argparse
import requests
import logging
import threading
from logging.handlers import RotatingFileHandler


CHECK_INTERVAL = 0.5  # seconds between file mtime checks

_log_dir = os.path.join(os.getcwd(), "logs")
os.makedirs(_log_dir, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
    handlers=[
        RotatingFileHandler(
            os.path.join(_log_dir, "msport_monitor.log"), maxBytes=10_000_000, backupCount=5
        ),
        logging.StreamHandler(),
    ],
)


SITE_DB = "site.db"


def open_ro(path: str) -> sqlite3.Connection:
    """Open a SQLite DB in read-only mode (no write locks)."""
    uri = f"file:{os.path.abspath(path)}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def read_listen_ip() -> str:
    """Read the host IP from site.db (same source as msport_display_proxy)."""
    with sqlite3.connect(SITE_DB) as conn:
        row = conn.execute(
            "SELECT params FROM microservices WHERE path = 'msport_display_proxy.py'"
        ).fetchone()
    return row[0] if row else "localhost"


def set_d1(driver_id: int | str):
    """Write D1 into active_drivers in site.db."""
    with sqlite3.connect(SITE_DB) as conn:
        conn.execute("UPDATE active_drivers SET D1 = ?", (str(driver_id),))
        conn.commit()
    logging.info("D1 set to %s", driver_id)


def call_update_event(host: str):
    """GET /api/update_event?active=true — same call as the display proxy."""
    url = f"http://{host}:7777/api/update_event?active=true"
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            logging.info("update_event OK")
        else:
            logging.error("update_event returned %s", r.status_code)
    except Exception as e:
        logging.error("update_event failed: %s", e)


def get_mtime(path: str):
    try:
        return os.path.getmtime(path)
    except (FileNotFoundError, OSError):
        return None


def read_online_params(online_db: str) -> tuple[int, int]:
    """Return (event_number, heat_number) from Online.scdb."""
    with open_ro(online_db) as conn:
        cur = conn.execute(
            "SELECT C_PARAM, C_VALUE FROM TPARAMETERS "
            "WHERE C_PARAM='EVENT' OR C_PARAM='HEAT'"
        )
        rows = {row[0]: row[1] for row in cur.fetchall()}
    event = int(rows.get("EVENT", 0))
    heat = int(rows.get("HEAT", 1))
    return event, heat


def event_db_name(event_num: int) -> str:
    return f"Event{event_num:03d}Ex.scdb"


def read_startlist(event_db: str, heat: int) -> list[dict]:
    """Return startlist ordered by C_LINE."""
    table = f"TSTARTLIST_HEAT{heat}"
    with open_ro(event_db) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(f"SELECT C_LINE, C_NUM, C_START FROM {table} ORDER BY C_LINE")
        return [dict(row) for row in cur.fetchall()]


# C_PENALTY values used by MSport for special statuses (non-zero = not on track)
PENALTY_LABELS = {
    1: "DSQ",
    2: "DNF",
    3: "DNS",
}


def read_timeinfos(event_db: str, heat: int) -> dict[int, dict]:
    """Return {C_NUM: {C_NUM, C_STATUS, C_TIME, C_PENALTY}} mapping."""
    table = f"TTIMEINFOS_HEAT{heat}"
    with open_ro(event_db) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(f"SELECT C_NUM, C_STATUS, C_TIME, C_PENALTY FROM {table}")
        return {row["C_NUM"]: dict(row) for row in cur.fetchall()}


def is_on_track(info: dict) -> bool:
    """Driver is on track only if: no finish time, no DSQ/DNF/DNS penalty,
    and C_STATUS == 0 (guards against statuses set before C_PENALTY is written)."""
    return info["C_TIME"] == 0 and info["C_PENALTY"] == 0 and info["C_STATUS"] == 0


def ms_to_str(ms: int) -> str:
    if ms <= 0:
        return "0.000"
    total_s, millis = divmod(ms, 1000)
    minutes, seconds = divmod(total_s, 60)
    if minutes:
        return f"{minutes}:{seconds:02d}.{millis:03d}"
    return f"{seconds}.{millis:03d}"


def _delayed_d1_and_update(next_driver: int, delay: float, host: str):
    """Background thread: wait, then set D1 and fire update_event."""
    logging.info("Waiting %ss before switching D1 to #%s", delay, next_driver)
    time.sleep(delay)
    set_d1(next_driver)
    call_update_event(host)


def get_newly_finished(
    prev: dict[int, dict], curr: dict[int, dict]
) -> list[int]:
    """Return driver numbers that newly crossed the finish line.
    A finish is detected when a driver transitions from on-track
    (C_TIME==0, C_PENALTY==0, C_STATUS==0) to having a finish time (C_TIME > 0).
    """
    finished = []
    for num, info in curr.items():
        prev_info = prev.get(num)
        if prev_info is None:
            continue
        was_on_track = is_on_track(prev_info)
        now_finished = info["C_TIME"] > 0
        if was_on_track and now_finished:
            finished.append(num)
    return finished


def analyze(
    startlist: list[dict],
    timeinfos: dict[int, dict],
    prev_timeinfos: dict[int, dict],
    heat: int,
    host: str,
    prev_active_driver: int | None,
    delay: float,
) -> int | None:
    """Compute state, trigger D1 updates and update_event calls, print status.

    D1 tracks whoever is currently on track. When the track is empty it shows
    the next driver to start. The delay (if set) only applies on a finish: the
    scoreboard refreshes immediately, but D1 doesn't switch until after the wait.

    Returns the active_driver value to be used as prev_active_driver next call.
    """

    on_track: list[int] = []
    done: set[int] = set()

    for num, info in timeinfos.items():
        if is_on_track(info):
            on_track.append(num)
        else:
            done.add(num)

    accounted_for = set(on_track) | done

    next_driver = None
    for entry in startlist:
        if entry["C_NUM"] not in accounted_for:
            next_driver = entry["C_NUM"]
            break

    # D1 = on-track driver while someone is running; next to start when clear
    active_driver = on_track[0] if on_track else next_driver

    # --- Finish-line detection ---
    newly_finished = get_newly_finished(prev_timeinfos, timeinfos)
    if newly_finished:
        logging.info("Finish line crossed by: %s", newly_finished)
        call_update_event(host)  # always fire immediately on finish

        if delay > 0 and active_driver is not None:
            # Scoreboard already updated above; switch D1 after delay then update again
            threading.Thread(
                target=_delayed_d1_and_update,
                args=(active_driver, delay, host),
                daemon=True,
            ).start()
        elif active_driver is not None and active_driver != prev_active_driver:
            set_d1(active_driver)

    # --- D1 update for non-finish changes (driver starts, heat switch, etc.) ---
    elif active_driver != prev_active_driver and active_driver is not None:
        set_d1(active_driver)

    # --- Print status ---
    print(f"\n{'='*50}")
    print(f"  Heat {heat} — Status Update")
    print(f"{'='*50}")

    if on_track:
        print(f"  ON TRACK   : {', '.join(f'#{n}' for n in on_track)}")
    else:
        print(f"  ON TRACK   : (none)")

    if next_driver is not None:
        print(f"  NEXT START : #{next_driver}")
    else:
        print(f"  NEXT START : (all drivers started)")

    print(f"\n  Start order:")
    for entry in startlist:
        num = entry["C_NUM"]
        info = timeinfos.get(num)
        if info is None:
            status = "  waiting"
        elif is_on_track(info):
            status = "  ON TRACK"
        elif info["C_PENALTY"] != 0:
            label = PENALTY_LABELS.get(info["C_PENALTY"], f"PENALTY({info['C_PENALTY']})")
            status = f"  {label}"
        else:
            status = f"  finished: {ms_to_str(info['C_TIME'])}"
        print(f"    [{entry['C_LINE']:2d}] #{num:<5}{status}")

    print()
    return active_driver


def main():
    parser = argparse.ArgumentParser(description="MSport DB monitor (read-only)")
    parser.add_argument(
        "--dir",
        default=".",
        help="Directory containing the .scdb files (default: current dir)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=CHECK_INTERVAL,
        help=f"Poll interval in seconds (default: {CHECK_INTERVAL})",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Race control host IP for update_event calls (default: read from site.db)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0,
        metavar="SECONDS",
        help=(
            "Seconds to wait after a finish before switching D1 to the next driver. "
            "When set: update_event fires immediately on finish, then after the delay "
            "D1 is updated and update_event fires again (default: 0, switch immediately)"
        ),
    )
    args = parser.parse_args()

    db_dir = args.dir
    interval = args.interval
    online_db = os.path.join(db_dir, "Online.scdb")

    host = args.host or read_listen_ip()
    delay = args.delay
    logging.info("MSport Monitor starting — watching: %s", online_db)
    logging.info("update_event host: %s  |  poll interval: %ss  |  D1 switch delay: %ss", host, interval, delay)

    last_online_mtime = None
    last_event_mtime = None
    current_event: int | None = None
    current_heat: int | None = None
    event_db: str | None = None
    prev_timeinfos: dict[int, dict] = {}
    prev_active_driver: int | None = None

    while True:
        try:
            online_mtime = get_mtime(online_db)

            if online_mtime is None:
                logging.warning("%s not found, retrying...", online_db)
                time.sleep(interval)
                continue

            if online_mtime != last_online_mtime:
                last_online_mtime = online_mtime
                try:
                    event, heat = read_online_params(online_db)
                except Exception as e:
                    logging.error("Reading Online.scdb: %s", e)
                    time.sleep(interval)
                    continue

                if event != current_event or heat != current_heat:
                    current_event = event
                    current_heat = heat
                    event_db = os.path.join(db_dir, event_db_name(event))
                    last_event_mtime = None  # force re-read
                    prev_timeinfos = {}
                    prev_active_driver = None
                    logging.info("Event=%s  Heat=%s  → %s", event, heat, event_db_name(event))

            if event_db is None or current_heat is None:
                time.sleep(interval)
                continue

            event_mtime = get_mtime(event_db)

            if event_mtime is None:
                logging.warning("%s not found", event_db)
                time.sleep(interval)
                continue

            if event_mtime != last_event_mtime:
                last_event_mtime = event_mtime
                try:
                    startlist = read_startlist(event_db, current_heat)
                    timeinfos = read_timeinfos(event_db, current_heat)
                    prev_active_driver = analyze(
                        startlist, timeinfos, prev_timeinfos,
                        current_heat, host, prev_active_driver, delay,
                    )
                    prev_timeinfos = timeinfos
                except Exception as e:
                    logging.error("Reading event DB: %s", e)

        except KeyboardInterrupt:
            logging.info("Exiting.")
            sys.exit(0)
        except Exception as e:
            logging.error("Unexpected: %s", e)

        time.sleep(interval)


if __name__ == "__main__":
    main()
