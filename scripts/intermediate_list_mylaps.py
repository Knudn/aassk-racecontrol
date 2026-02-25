import os
import time
import sqlite3
import requests
import xml.etree.ElementTree as ET
import json
import sys
import paho.mqtt.publish as publish
from sqlalchemy import create_engine, Column, Integer, Text, JSON, Boolean, event
from sqlalchemy.orm import declarative_base, Session
import zlib
import logging
from logging.handlers import RotatingFileHandler

_log_dir = os.path.join(os.getcwd(), 'logs')
os.makedirs(_log_dir, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
    handlers=[
        RotatingFileHandler(os.path.join(_log_dir, 'intermediate_list_mylaps.log'), maxBytes=10_000_000, backupCount=5),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# Configuration
DB_PATH = "site.db"
STATE_DB_PATH = "sqlite:////mnt/intermediate/race_state.db"

MQTT_BROKER = "127.0.0.1"
MQTT_TOPIC = "start/mylaps_inter"

# SQLAlchemy setup
Base = declarative_base()

class ScheduleEntry(Base):
    """One row per run/heat from schedule.xml"""
    __tablename__ = "schedule_entries"
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_name = Column(Text, nullable=False)
    heat = Column(Text, nullable=False)
    data = Column(JSON, nullable=False)
    event_checksum = Column(Text, nullable=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.event_checksum:
            heat = str(self.heat) if self.heat is not None else ""
            self.event_checksum = create_event_id_checksum(f"{self.run_name} {heat}")

@event.listens_for(ScheduleEntry, 'before_insert')
def set_event_checksum(mapper, connection, target):
    if target.event_checksum is None:
        heat = str(target.heat) if target.heat is not None else ""
        target.event_checksum = create_event_id_checksum(f"{target.run_name} {heat}")


class RaceEntry(Base):
    """One flat row per driver per heat from current.xml"""
    __tablename__ = "race_entries"
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_name = Column(Text, nullable=False)
    heat = Column(Text, nullable=False)
    active_event = Column(Boolean, nullable=False, default=False)
    event_id = Column(Text, nullable=False)
    cid = Column(Integer, nullable=False)
    data = Column(JSON, nullable=False)


engine = create_engine(
    STATE_DB_PATH,
    json_serializer=lambda obj: json.dumps(obj, ensure_ascii=False),
    connect_args={"timeout": 15},
)
Base.metadata.create_all(engine)

# Load global config
with sqlite3.connect(DB_PATH) as con:
    cur = con.cursor()
    g_config = cur.execute(
        "SELECT wl_cross_title, wl_bool, wl_title, race_type, msport_tm from global_config;"
    ).fetchone()

if int(g_config[4]) == 1:
    logger.info("Not using Orbits/Mylaps. Exiting.")
    sys.exit()

wl_bool = g_config[1]

if bool(wl_bool) == True:
    wl_title = g_config[2]
    wl_cross_title = g_config[0]

# 1 = Bakkecross, 5 = Cross, 4 = Vanncross
race_type = int(g_config[3])

if race_type == 2 or race_type == 3:
    logger.warning("Wrong race type configured. Check global-config. Exiting.")
    sys.exit()

event_name = ""
active_event = []


def create_event_id_checksum(event_entry):
    #The checksum will be based on str(run_name + heat)
    checksum = zlib.crc32(event_entry.encode())
    logger.debug("Checksum: %08x for %s", checksum, event_entry)
    return f"{checksum:08x}"


def upsert_schedule(run_name, heat, data):

    with Session(engine) as session:
        existing = session.query(ScheduleEntry).filter_by(
            run_name=run_name, heat=str(heat)
        ).first()
        if existing:
            existing.data = data
        else:
            session.add(ScheduleEntry(
                run_name=run_name, heat=str(heat), data=data
            ))
        session.commit()


def get_schedule_entry(run_name, heat):
    with Session(engine) as session:
        row = session.query(ScheduleEntry).filter_by(
            run_name=run_name, heat=str(heat)
        ).first()
        return row.data if row else None


def get_all_schedule_keys():
    """Returns set of (run_name, heat) tuples currently in schedule"""
    with Session(engine) as session:
        rows = session.query(ScheduleEntry.run_name, ScheduleEntry.heat).all()
        return set((r[0], r[1]) for r in rows)


def get_schedule_run_names():
    with Session(engine) as session:
        rows = session.query(ScheduleEntry.run_name).distinct().all()
        return [r[0] for r in rows]


def clear_schedule():
    with Session(engine) as session:
        session.query(ScheduleEntry).delete()
        session.commit()



def upsert_driver(run_name, heat, cid, data):
    with Session(engine) as session:
        existing = session.query(RaceEntry).filter_by(
            run_name=run_name, heat=str(heat), cid=int(cid)
        ).first()

        raw = json.dumps(data)
        data = json.loads(raw.replace('\\\\u', '\\u'))

        checksum = create_event_id_checksum(run_name + " " + heat)

        if existing:
            existing.data = data
        else:
            session.add(RaceEntry(
                run_name=run_name, event_id=checksum, active_event=True, heat=str(heat), cid=int(cid), data=data
            ))
        session.commit()


def upsert_drivers_bulk(run_name, heat, drivers):
    """Insert all drivers for a heat in a single session to reduce DB churn."""
    checksum = create_event_id_checksum(run_name + " " + str(heat))
    with Session(engine) as session:
        for data in drivers:
            raw = json.dumps(data)
            data = json.loads(raw.replace('\\\\u', '\\u'))
            try:
                cid = int(data["cid"])
            except (ValueError, TypeError):
                logger.warning("Skipping driver with invalid cid: %s", data.get('cid'))
                continue
            existing = session.query(RaceEntry).filter_by(
                run_name=run_name, heat=str(heat), cid=cid
            ).first()
            if existing:
                existing.data = data
            else:
                session.add(RaceEntry(
                    run_name=run_name, event_id=checksum, active_event=True, heat=str(heat), cid=cid, data=data
                ))
        session.commit()


def get_drivers(run_name, heat):
    with Session(engine) as session:
        rows = session.query(RaceEntry).filter_by(
            run_name=run_name, heat=str(heat)
        ).all()
        return [row.data for row in rows]


def clear_heat(run_name, heat):
    with Session(engine) as session:
        session.query(RaceEntry).filter_by(
            run_name=run_name, heat=str(heat)
        ).delete()
        session.commit()

def clear_active_state():
    with Session(engine) as session:
        logger.info("Clearing active event state")
        entries = session.query(RaceEntry).filter_by(active_event=True).all()
        for a in entries:
            a.active_event = False
        session.commit()

def clear_event(run_name):
    with Session(engine) as session:
        session.query(RaceEntry).filter_by(run_name=run_name).delete()
        session.query(ScheduleEntry).filter_by(run_name=run_name).delete()
        session.commit()


def clear_all():
    with Session(engine) as session:
        session.query(RaceEntry).delete()
        session.query(ScheduleEntry).delete()
        session.commit()


def sync_to_schedule():
    """Remove any race entries that no longer exist in the schedule"""
    schedule_keys = get_all_schedule_keys()
    schedule_runs = set(k[0] for k in schedule_keys)

    with Session(engine) as session:
        # Get all unique run_name/heat combos in race entries
        race_keys = session.query(RaceEntry.run_name, RaceEntry.heat).distinct().all()

        for run_name, heat in race_keys:
            if run_name not in schedule_runs:
                logger.info("Schedule removed event: %s, cleaning up", run_name)
                session.query(RaceEntry).filter_by(run_name=run_name).delete()
            elif (run_name, heat) not in schedule_keys:
                logger.info("Schedule removed heat %s from %s, cleaning up", heat, run_name)
                session.query(RaceEntry).filter_by(
                    run_name=run_name, heat=heat
                ).delete()

        session.commit()


# --- XML parsing ---

def xml_to_dict(file):
    if type(file) == str:
        with open(file, "r") as f:
            file_read = f.read()
        element = ET.fromstring(file_read)
    else:
        element = file
    result = dict(element.attrib)

    if element.text and element.text.strip():
        result["_text"] = element.text.strip()

    for child in element:
        if len(child.items()) == 1 and race_type != 5:
            if child.items()[0][1] == "timeofday":
                child.text = ""
            if child.items()[0][1] == "racetime":
                child.text = ""

        child_data = xml_to_dict(child)
        if child.tag in result:
            if not isinstance(result[child.tag], list):
                result[child.tag] = [result[child.tag]]
            result[child.tag].append(child_data)
        else:
            result[child.tag] = child_data

    return result


# --- Helpers ---

def normalize_run_name(groupname, runname, runtype):
    if runtype == "Qualifying":
        try:
            heat = runname[-1]
            norm_grup_name = groupname + " - Kvalifisering"
            heats = 0
        except Exception as err:
            heats = 1
            norm_grup_name = runname
            heat = 1
    elif runtype == "Race":
        if "Kvali" in runname:
            heats = runname[-1]
            heat = runname[-1]
            norm_grup_name = groupname + " - Kvalifisering"
        elif "C" in runname:
            heats = runname[-1]
            norm_grup_name = groupname + " - C Finale"
            heat = runname[-1]
        elif "B" in runname:
            norm_grup_name = groupname + " - B Finale"
            heats = runname[-1]
            heat = runname[-1]
        elif len(runname.split("-")) == 2:
            norm_grup_name = groupname + " - " + runname.split("-")[0]
            heats = runname[-1]
            heat = runname[-1]
        else:
            heats = 1
            heat = 1
            norm_grup_name = groupname + " - " + runname
    else:
        heats = 1
        heat = 1
        norm_grup_name = groupname + " - " + runname

    return heat, norm_grup_name, heats


def get_event_name_from_xml():
    file_dict = xml_to_dict("/mnt/test/current.xml")
    for b in file_dict["label"]:
        if b["type"] == "eventname":
            return b["_text"]
    return ""


def _parse_time_to_seconds(value):
    """Parse a time string like MM:SS or HH:MM:SS to seconds. Returns 0 for placeholders like -??-."""
    try:
        parts = value.split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        else:
            return int(value)
    except (ValueError, AttributeError):
        return 0


def get_time_data(timetogo, racetime, curr_time):
    from datetime import datetime

    if len(curr_time.split(":")) == 3:
        time_format = "%H:%M:%S"
    else:
        time_format = "%M:%S"
    try:
        dt = datetime.strptime(curr_time, time_format).replace(
            year=datetime.now().year, month=datetime.now().month, day=datetime.now().day
        )
        curr_epoch = int(dt.timestamp())
    except (ValueError, AttributeError):
        curr_epoch = 0

    race_time_sec = _parse_time_to_seconds(racetime)
    timetogo_sec = _parse_time_to_seconds(timetogo)

    finishtime = curr_epoch + timetogo_sec
    starttime = curr_epoch - race_time_sec
    return starttime, finishtime, timetogo_sec


def set_active_event(event_id):
    global event_name

    json_data = {
        "event_id": event_id,
        "push_to_room": True,
    }

    try:
        requests.post(
            "http://192.168.1.50:7777/api/set_active_state",
            json=json_data,
            verify=False,
            timeout=5,
        )
    except requests.exceptions.RequestException as e:
        logger.error("Error setting active event: %s", e)


def extract_driver_data(data):
    tmp_driver_data_lst = []
    class_lst = []

    if isinstance(data, dict):
        data = [data]
    for a in data:
        first_name = a["firstname"]
        last_name = a["lastname"]
        laps = a["laps"] if a["laps"] != "" else 0
        pen = a["position"]
        cid = a["no"]
        club = a["additional5"]
        snowmobile = a["additional1"]
        best_time = a["besttime"]
        last_time = a["lasttime"]
        driver_class = a["class"]
        gap = a["gap"]
        if best_time == "":
            best_time = 0
        if a["totaltime"] == "":
            totale_time = 0
        else:
            totale_time = a["totaltime"]
        
        if driver_class not in class_lst:
            class_lst.append(driver_class)

        if str(pen).upper() == "DQ":
            penalty = "DSQ"
        elif "D" in str(pen).upper():
            penalty = ""
        else:
            penalty = ""


        tmp_driver_data = {
            "cid": cid,
            "first_name": first_name,
            "last_name": last_name,
            "club": club,
            "snowmobile": snowmobile,
            "totaltime": totale_time,
            "laps": laps,
            "position": pen,
            "best_time": best_time,
            "last_lap_time": last_time,
            "class":driver_class,
            "gap":gap,
            "penalty":penalty,
        }

        tmp_driver_data_lst.append(tmp_driver_data)
    if len(class_lst) > 1:
        multi_class = True
    else:
        multi_class = False

    return tmp_driver_data_lst, multi_class


def index_current():
    """Restore state from existing race_state.db on startup"""
    global event_name, active_event

    with Session(engine) as session:
        schedule_count = session.query(ScheduleEntry).count()
        race_count = session.query(RaceEntry).count()

        if schedule_count == 0:
            logger.info("No existing state in DB, starting fresh")
            return

        logger.info("Restored state: %d schedule entries, %d race entries", schedule_count, race_count)

        # Restore event_name from first schedule entry
        first_schedule = session.query(ScheduleEntry).first()
        if first_schedule and first_schedule.data.get("event_name"):
            event_name = first_schedule.data["event_name"]
            logger.info("Restored event name: %s", event_name)

        # Restore active_event from the active race entry
        active_entry = session.query(RaceEntry).filter_by(active_event=True).first()
        if active_entry:
            active_event = [active_entry.heat, active_entry.run_name]
            logger.info("Restored active event: %s", active_event)


def proc_current(current_dict):
    """Process current.xml data and update race entries"""
    global event_name
    heat_has_timentries = False
    current_flag = None
    laps_to_go = None

    for a in current_dict["label"]:
        if a["type"] == "runname":
            run_name = a["_text"]
        elif a["type"] == "groupname":
            group_name = a["_text"]
        elif a["type"] == "runtype":
            type_name = a["_text"]
            if type_name == "Q":
                type_name = "Qualifying"
            elif type_name == "R":
                type_name = "Race"
            elif type_name == "P":
                type_name = "Practice"
        elif a["type"] == "leadermargin" and "_text" in a:
            heat_has_timentries = True
        elif a["type"] == "flag":
            current_flag = a["_text"]
        elif a["type"] == "lapstogo" and "_text" in a:
            laps_to_go = a["_text"]
    logger.debug("proc_current: %s %s %s", group_name, run_name, type_name)
    heat, run_name, heats = normalize_run_name(group_name, run_name, type_name)
    logger.debug("Normalized: heat=%s run=%s heats=%s", heat, run_name, heats)
    schedule = get_schedule_entry(run_name, heat)
    if not schedule:
        return

    if (
        not heat_has_timentries
        and (current_flag == "none" or current_flag == "warmup")
        and laps_to_go is not None
    ):
        try:
            schedule["laps"] = int(laps_to_go)
        except (ValueError, TypeError):
            schedule["laps"] = 0
        upsert_schedule(run_name, heat, schedule)

    finish_on_lap = schedule["laps"]

    clear_heat(run_name, heat)

    

    if "result" in current_dict["results"]:
        driver_data, multi_class = extract_driver_data(current_dict["results"]["result"])
        timedata = schedule.get("timedata", "")
        time_to_go_parts = timedata.split(":")
        try:
            time_to_go = int(time_to_go_parts[-1]) if time_to_go_parts[-1] else 0
        except (ValueError, IndexError):
            time_to_go = 0
        event_id = create_event_id_checksum(run_name + " " + heat)
        for driver in driver_data:
            driver["run_name"] = run_name
            driver["event_name"] = event_name
            driver["heat"] = str(heat)
            driver["timedata"] = timedata
            driver["time_to_go"] = time_to_go
            driver["multi_class"] = multi_class
            driver["event_id"] = event_id
            try:
                driver["laps_to_go"] = 0 if laps_to_go is None else int(laps_to_go)
            except (ValueError, TypeError):
                driver["laps_to_go"] = 0
            if (driver["laps_to_go"] == 0 and driver["time_to_go"] == 0 and driver["totaltime"]) or current_flag == "finish":
                driver["finished"] = True
            else:
                driver["finished"] = False
        upsert_drivers_bulk(run_name, heat, driver_data)
            

def build_schedule_api(sc_data):
    data = {"table_data": json.dumps(sc_data), "src": "orbits"}
    logger.debug("Posting schedule: %s", data)
    try:
        requests.post(
            "http://192.168.1.50:7777/admin/active_events", data=data, verify=False,
            timeout=5,
        )
    except requests.exceptions.RequestException as e:
        logger.error("Error posting schedule: %s", e)


def update_schedule(entry):
    global event_name

    if event_name == "":
        event_name = get_event_name_from_xml()

    current_schedule_keys = get_all_schedule_keys()
    new_schedule_keys = set()
    schedule_lst = []

    for k, results in enumerate(entry["results"]["result"]):
        k += 1
        heat, norm_group_name, heats = normalize_run_name(
            results["groupname"], results["runname"], results["runtype"]
        )
        schedule_lst.append({"name": norm_group_name, "run": heat, "sort_order": k})
        new_schedule_keys.add((norm_group_name, str(heat)))

        existing = get_schedule_entry(norm_group_name, heat)

        if existing:
            logger.debug("Found: %s", norm_group_name)
            existing["sort_order"] = k
            upsert_schedule(norm_group_name, str(heat), existing)
        else:
            logger.info("Added schedule entry: %s", norm_group_name)

            event_checksum = create_event_id_checksum(norm_group_name + " " + heat)
            upsert_schedule(norm_group_name, str(heat), {
                "event_name": event_name,
                "heats": heats,
                "laps": 0,
                "time": results["datetime"],
                "timedata": "",
                "sort_order": k,
                "event_checksum": event_checksum,
            })

    build_schedule_api(schedule_lst)

    # Remove anything no longer in schedule
    removed = current_schedule_keys - new_schedule_keys
    for run_name, heat in removed:
        logger.info("Schedule removed: %s heat %s, cleaning up", run_name, heat)
        clear_heat(run_name, heat)
        with Session(engine) as session:
            session.query(ScheduleEntry).filter_by(
                run_name=run_name, heat=heat
            ).delete()
            session.commit()

    # Also sync race entries (catches any stragglers)
    sync_to_schedule()


# --- Main loop ---

def file_monitor():
    global active_event
    global event_name

    tracking_dict = {}
    old_entry = {}
    last_sc = ""
    sleep_time = 0.5
    old_finishtime = 0
    old_startime = 0
    old_timetogo_sec = 999
    old_flag_state = {}
    first_run = True

    index_current()

    # If we restored schedule state from DB, don't wait for schedule.xml to change
    # before processing current.xml — otherwise current.xml gets skipped on restart.
    with Session(engine) as session:
        sc_proc = session.query(ScheduleEntry).count() > 0
    if sc_proc:
        logger.info("Restored schedule from DB, sc_proc=True")

    while True:
        try:
            with os.scandir("/mnt/test/") as dir_files:
                for file in dir_files:
                    if "current.xml" not in file.path and "schedule.xml" not in file.path:
                        continue
                        
                    if file.path not in tracking_dict:
                        tracking_dict[file.path] = 0
                    
                    if tracking_dict[file.path] < os.path.getmtime(file.path):
                        tracking_dict[file.path] = os.path.getmtime(file.path)

                        if "current.xml" in file.path and sc_proc:
                            file_dict = xml_to_dict(file.path)
                            
                            if "result" not in file_dict.get("results", {}):
                                no_drivers = True
                            if file_dict != old_entry:
                                trigger_update = False
                                runname = ""
                                groupname = ""
                                flag_state = ""
                                type_name = ""
                                curr_time = "00:00:00"
                                racetime = "00:00"
                                timetogo = "00:00"

                                for a in file_dict["label"]:
                                    if a["type"] == "runname":
                                        runname = a["_text"]
                                    elif a["type"] == "groupname":
                                        groupname = a["_text"]
                                    elif a["type"] == "flag":
                                        flag_state = a["_text"]
                                    elif a["type"] == "runtype":
                                        type_name = a["_text"]
                                        if type_name == "Q":
                                            type_name = "Qualifying"
                                        elif type_name == "R":
                                            type_name = "Race"
                                        elif type_name == "P":
                                            type_name = "Practice"
                                    elif a["type"] == "timeofday" and race_type == 5:
                                        curr_time = a["_text"]
                                    elif a["type"] == "racetime" and len(a) > 1:
                                        racetime = a["_text"]
                                    elif a["type"] == "racetime" and len(a) == 1:
                                        racetime = "00:00"
                                    elif a["type"] == "timetogo" and len(a) > 1:
                                        timetogo = a["_text"]
                                    elif a["type"] == "timetogo" and len(a) == 1:
                                        timetogo = "00:00"

                                if old_flag_state != flag_state:
                                    current_flag = json.dumps({"current_flag": flag_state})
                                    logger.info("Flag state changed: %s", current_flag)
                                    try:
                                        publish.single(
                                            MQTT_TOPIC,
                                            payload=current_flag,
                                            hostname=MQTT_BROKER,
                                        )
                                    except Exception as e:
                                        logger.error("MQTT publish error: %s", e)
                                    trigger_update = True
                                    old_flag_state = flag_state

                                if race_type == 5:
                                    if timetogo == "00:00" and racetime != "00:00":
                                        run_starttime, run_finishtime, timetogo_sec = (
                                            get_time_data(timetogo, racetime, curr_time)
                                        )

                                    if "results" not in old_entry:
                                        old_entry["results"] = {}

                                    if timetogo != "00:00":
                                        run_starttime, run_finishtime, timetogo_sec = (
                                            get_time_data(timetogo, racetime, curr_time)
                                        )
                                        if (
                                            old_finishtime != run_finishtime
                                            or old_startime != run_starttime
                                        ) and timetogo_sec != old_timetogo_sec:
                                            old_startime = run_starttime
                                            old_finishtime = run_finishtime
                                            old_timetogo_sec = timetogo_sec
                                            trigger_update = True

                                    if file_dict["results"] != old_entry["results"]:
                                        trigger_update = True

                                elif race_type != 5:
                                    trigger_update = True

                                heat, run_name, heats = normalize_run_name(
                                    groupname, runname, type_name
                                )
                                
                                if active_event != [heat, run_name] or first_run == True:
                                    logger.info("Active event update: %s heat %s", run_name, heat)
                                    event_id = create_event_id_checksum(run_name + " " + heat)
                                    set_active_event(event_id)

                                    clear_active_state()
                                    active_event = [heat, run_name]
                                    old_entry = {}  # reset so results comparison starts fresh for new heat
                                    sleep_time = 1
                                    trigger_update = True  # always process when heat changes or on startup
                                else:
                                    sleep_time = 0.5
                                
                                first_run = False

                                if race_type == 5:
                                    schedule = get_schedule_entry(run_name, heat)
                                    if schedule:
                                        schedule["timedata"] = (
                                            f"{run_starttime}:{run_finishtime}:{timetogo_sec}"
                                        )
                                        upsert_schedule(run_name, heat, schedule)

                                if trigger_update == False:
                                    logger.debug("No trigger, continuing")
                                    continue

                                proc_current(file_dict)
                                old_entry = file_dict
                                logger.info("Event data updated: %s heat %s", run_name, heat)
                                event_id = create_event_id_checksum(run_name + " " + heat)
                                try:
                                    requests.get(f"http://192.168.1.50:7777/api/update_event?active=True", timeout=5)
                                except requests.exceptions.RequestException as e:
                                    logger.error("Error triggering event update: %s", e)

                        elif "schedule.xml" in file.path:
                            file_dict = xml_to_dict(file.path)
                            if last_sc != file_dict:
                                logger.info("Schedule updated")
                                update_schedule(file_dict)
                            sc_proc = True
                            last_sc = file_dict

        except Exception as e:
            logger.error("Error in main loop: %s", e)

        time.sleep(sleep_time)


file_monitor()