import os
import time
import shutil
import sqlite3
import requests
import xml.etree.ElementTree as ET
import traceback
from typing import Dict, Set

# Configuration
FIFO_PATH = '/tmp/file_monitor_fifo'
ACTIVE_EVENT_QUERY = "SELECT C_VALUE FROM TPARAMETERS WHERE C_PARAM = 'HEAT' OR C_PARAM = 'EVENT';"
MODE_QUERY = "SELECT C_VALUE FROM TPARAMETERS WHERE C_PARAM='MODULE';"
event_name_sch = ""
DB_PATH = "site.db"

with sqlite3.connect(DB_PATH) as con:
    cur = con.cursor()
    g_config = cur.execute("SELECT wl_cross_title, wl_bool, wl_title from global_config;").fetchone()

wl_bool = g_config[1]

if bool(wl_bool) == True:
    wl_title = g_config[2]
    wl_cross_title = g_config[0]

def xml_to_dict(element):
    """Convert XML element to dictionary"""
    result = dict(element.attrib)
    
    if element.text and element.text.strip():
        result['_text'] = element.text.strip()
    
    for child in element:
        child_data = xml_to_dict(child)
        
        if child.tag in result:
            if not isinstance(result[child.tag], list):
                result[child.tag] = [result[child.tag]]
            result[child.tag].append(child_data)
        else:
            result[child.tag] = child_data
    
    return result


class FileMonitor:
    """Main file monitoring class"""
    
    def __init__(self, source_dir: str, intermediate_dir: str, host: str = "localhost"):
        self.source_dir = source_dir
        self.intermediate_dir = intermediate_dir
        self.host = host
        
        # State tracking
        self.schedule = {}  # event_key -> {heats, runs, ...}
        self.event_db_mapping = {}  # event_key -> db_filename
        self.event_drivers = {}  # event_key -> set of CIDs (total across all heats)
        self.event_drivers_per_heat = {}  # (event_key, heat) -> set of CIDs
        
        self.last_modified_times = {}
        self.last_schedule_data = ""
        self.last_current_data = ""
        self.last_event_drivers = {}  # event_key -> set of CIDs from last current.xml
        
        self.active_state = {"event": "000", "heat": 0, "mode": 0}
        self.startlist_dict = []
        
        # Index existing databases
        self._index_databases()
    
    def _index_databases(self):
        """Index existing EventX.scdb files"""
        if not os.path.exists(self.intermediate_dir):
            os.makedirs(self.intermediate_dir)
        
        for filename in os.listdir(self.intermediate_dir):
            if filename.endswith(".scdb") and "Event" in filename and "Ex" not in filename:

                db_path = os.path.join(self.intermediate_dir, filename)
                
                try:
                    with sqlite3.connect(db_path) as conn:
                        cursor = conn.cursor()
                        cursor.execute("SELECT C_VALUE FROM TPARAMETERS WHERE C_PARAM='TITLE1' OR C_PARAM='TITLE2';")
                        params = cursor.fetchall()
                        
                        if len(params) >= 2:
                            title1 = params[0][0]
                            title2 = params[1][0]
                            event_key = f"{title1}|{title2}"
                            if bool(wl_bool):
                                if wl_title not in event_key:
                                    print("skipped", event_key)
                                    continue

                            self.event_db_mapping[event_key] = filename
                            cursor.execute("SELECT C_NUM FROM TCOMPETITORS;")
                            existing_cids = {str(row[0]) for row in cursor.fetchall()}
                            self.event_drivers[event_key] = existing_cids
                except:
                    pass
        
        print(f"Indexed {len(self.event_db_mapping)} event database(s)")
    
    def parse_schedule(self, schedule_path: str) -> bool:
        """Parse schedule.xml"""
        global event_name_sch
        try:
            with open(schedule_path, "r") as f:
                data = f.read()
            if event_name_sch == "":
                with open("/mnt/test/current.xml", "r") as f:
                    data_title1 = f.read()
                event_name_root = ET.fromstring(data_title1)
                event_name_dict = xml_to_dict(event_name_root)
                
                for a in event_name_dict["label"]:
                    if a["type"] == "eventname":
                        event_name_sch = a["_text"]

            # Quick check - if XML identical, skip
            if data == self.last_schedule_data:
                return False
            
            self.last_schedule_data = data
            
            root = ET.fromstring(data)
            schedule_dict = xml_to_dict(root)
            
            if "results" not in schedule_dict or "result" not in schedule_dict["results"]:
                return False
            
            result_list = schedule_dict["results"]["result"]
            if not isinstance(result_list, list):
                result_list = [result_list]
            
            new_schedule = {}
            
            for run_data in result_list:
                group_name = run_data.get("groupname", "")
                run_name = run_data.get("runname", "")
                run_type = run_data.get("runtype", "")
                datetime_str = run_data.get("datetime", "")
                
                if run_name == group_name:
                    continue
                
                # Normalize group name
                if run_type == "Qualifying":
                    if "KVALI" not in group_name.upper():
                        modified_group = group_name + " - Kvalifisering"
                    else:
                        modified_group = group_name
                else:
                    if "C-" in run_name or "C " in run_name:
                        modified_group = group_name + " - C"
                    elif "B-" in run_name or "B " in run_name:
                        modified_group = group_name + " - B"
                    else:
                        modified_group = group_name + " " + run_name
                
                event_key = f"{event_name_sch}|{modified_group}"
                if event_key not in new_schedule:
                    new_schedule[event_key] = {
                        "event_name": group_name,
                        "group_name": modified_group,
                        "heats": 0,
                        "runs": [],
                        "run_times": {}  # run_name -> datetime for sorting
                    }
                
                if run_name not in new_schedule[event_key]["runs"]:
                    new_schedule[event_key]["runs"].append(run_name)
                    new_schedule[event_key]["run_times"][run_name] = datetime_str
                    new_schedule[event_key]["heats"] += 1
            
            # Sort runs by datetime for each event
            for event_key in new_schedule:
                runs = new_schedule[event_key]["runs"]
                run_times = new_schedule[event_key]["run_times"]
                
                # Sort runs by their datetime
                sorted_runs = sorted(runs, key=lambda r: run_times.get(r, ""))
                new_schedule[event_key]["runs"] = sorted_runs
            
            # Detect changes in existing events
            old_event_keys = set(self.schedule.keys())
            new_event_keys = set(new_schedule.keys())
            
            # Events that disappeared from schedule
            removed_events = old_event_keys - new_event_keys
            
            # Events that stayed
            for event_key in (old_event_keys & new_event_keys):
                old_heats = self.schedule[event_key]["heats"]
                new_heats = new_schedule[event_key]["heats"]
                
                if old_heats != new_heats:
                    print(f"Schedule change: {event_key} heats {old_heats} -> {new_heats}")
                    if event_key in self.event_db_mapping:
                        self._update_heat_count(event_key, new_heats)
            
            # Handle removed events - check if they were just renamed
            for old_event_key in removed_events:
                # Extract base group name (before |)
                old_base_group = old_event_key.split("|")[0]
                
                # Look for new events with same base group
                renamed = False
                for new_event_key in (new_event_keys - old_event_keys):
                    new_base_group = new_event_key.split("|")[0]
                    
                    if old_base_group == new_base_group:
                        # Same base group, different run type - this is a rename
                        print(f"Event renamed: {old_event_key} -> {new_event_key}")
                        
                        if old_event_key in self.event_db_mapping:
                            # Update the database file with new information
                            db_filename = self.event_db_mapping[old_event_key]
                            new_info = new_schedule[new_event_key]
                            
                            self._update_event_info(
                                db_filename,
                                new_info["event_name"],
                                new_info["group_name"],
                                new_info["heats"]
                            )
                            
                            # Update mappings
                            self.event_db_mapping[new_event_key] = db_filename
                            del self.event_db_mapping[old_event_key]
                            
                            if old_event_key in self.event_drivers:
                                self.event_drivers[new_event_key] = self.event_drivers[old_event_key]
                                del self.event_drivers[old_event_key]
                            
                            if old_event_key in self.last_event_drivers:
                                self.last_event_drivers[new_event_key] = self.last_event_drivers[old_event_key]
                                del self.last_event_drivers[old_event_key]
                        
                        renamed = True
                        break
                
                # If not renamed, truly removed - delete files
                if not renamed and old_event_key in self.event_db_mapping:
                    db_filename = self.event_db_mapping[old_event_key]
                    self._delete_event_files(old_event_key, db_filename)

            
            self.schedule = new_schedule
            print(f"Schedule: {len(self.schedule)} events loaded")
            
            # Display heat order for verification
            for event_key, event_info in sorted(self.schedule.items()):
                print(f"\n{event_key}:")
                for idx, run_name in enumerate(event_info["runs"], 1):
                    time_str = event_info["run_times"].get(run_name, "??:??")
                    print(f"  Heat {idx}: {time_str} - {run_name}")
            
            return True
        
        except Exception as e:
            print(f"Error parsing schedule: {e}")
            return False
    
    def _update_event_info(self, db_filename: str, event_name: str, group_name: str, heats: int):
        """Update event information in database"""
        try:
            db_path = os.path.join(self.intermediate_dir, db_filename)
            
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE TPARAMETERS SET C_VALUE = ? WHERE C_PARAM = 'TITLE1';", (event_name,))
                cursor.execute("UPDATE TPARAMETERS SET C_VALUE = ? WHERE C_PARAM = 'TITLE2';", (group_name,))
                cursor.execute("UPDATE TPARAMETERS SET C_VALUE = ? WHERE C_PARAM = 'HEAT_NUMBER';", (str(heats),))
                conn.commit()
                print(f"  Updated {db_filename}: TITLE1={event_name}, TITLE2={group_name}, HEATS={heats}")
        except Exception as e:
            print(f"  Error updating event info: {e}")
    
    def _delete_event_files(self, event_key: str, db_filename: str):
        """Delete Event and EventEx database files for removed event"""
        try:
            # Delete main Event file
            db_path = os.path.join(self.intermediate_dir, db_filename)
            if os.path.exists(db_path):
                os.remove(db_path)
                print(f"Deleted: {db_filename}")
            
            # Delete Ex file
            ex_filename = db_filename.replace(".scdb", "Ex.scdb")
            ex_path = os.path.join(self.intermediate_dir, ex_filename)
            if os.path.exists(ex_path):
                os.remove(ex_path)
                print(f"Deleted: {ex_filename}")
            
            # Clean up internal state
            del self.event_db_mapping[event_key]
            if event_key in self.event_drivers:
                del self.event_drivers[event_key]
            if event_key in self.last_event_drivers:
                del self.last_event_drivers[event_key]
            
            print(f"Event removed: {event_key}")
        
        except Exception as e:
            print(f"Error deleting event files: {e}")
    
    def _update_heat_count(self, event_key: str, new_heats: int):
        """Update HEAT_NUMBER in existing database"""
        try:
            db_filename = self.event_db_mapping[event_key]
            db_path = os.path.join(self.intermediate_dir, db_filename)
            
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE TPARAMETERS SET C_VALUE = ? WHERE C_PARAM = 'HEAT_NUMBER';",
                    (str(new_heats),)
                )
                conn.commit()
                print(f"  Updated {db_filename}: HEAT_NUMBER = {new_heats}")
        except Exception as e:
            print(f"  Error updating heat count: {e}")
    
    def process_current(self, current_path: str) -> bool:
        """Process current.xml"""
        try:
            with open(current_path, "r") as f:
                data = f.read()
            
            # Parse XML
            root = ET.fromstring(data)
            current_dict = xml_to_dict(root)
            
            if "label" not in current_dict or "results" not in current_dict:
                return False
            # Quick check - compare only results section (ignore labels with timeofday)
            results = current_dict.get("results", {})
            results_str = str(results)  # Simple string comparison of results
            
            if results_str == self.last_current_data:
                return False
            
            self.last_current_data = results_str
            # Extract labels
            labels = current_dict.get("label", [])

            if not isinstance(labels, list):
                labels = [labels]
            
            group_name = ""
            event_name = ""
            run_name = ""
            run_type = ""
            
            for label in labels:
                t = label.get("type", "")
                if t == "groupname":
                    group_name = label.get("_text", "")
                elif t == "eventname":
                    event_name = label.get("_text", "")
                elif t == "runname":
                    run_name = label.get("_text", "")
                elif t == "runtype":
                    run_type = label.get("_text", "")
            
            # Normalize
            original_group = group_name
            if run_type == "Q":
                if "KVALI" not in group_name.upper():
                    group_name = group_name + " - Kvalifisering"
            else:
                if "C" in run_name:
                    group_name = group_name + " - C"
                elif "B" in run_name:
                    group_name = group_name + " - B"
                else:
                    group_name = group_name + " " + run_name
            
            # Extract drivers
            results = current_dict.get("results", {})
            result_list = results.get("result", [])
            if not isinstance(result_list, list):
                result_list = [result_list]
            
            driver_cids = set()
            drivers = {}
            
            for result in result_list:
                cid = str(result.get("no", ""))
                if cid:
                    driver_cids.add(cid)
                    drivers[cid] = {
                        "cid": cid,
                        "first_name": result.get("firstname", ""),
                        "last_name": result.get("lastname", ""),
                        "club": result.get("additional5", ""),
                        "team": result.get("additional1", "")
                    }
            
            if len(driver_cids) == 0:
                return False
            
            event_key = f"{event_name}|{group_name}"
            
            # Determine heat number from schedule
            heat_number = self._get_heat_number(event_key, run_name)
            
            # FIRST: Update Online.scdb with active event/heat so other programs see it immediately
            if heat_number > 0:
                self._update_online_scdb(event_key, heat_number)
            
            # Track drivers for this specific heat
            heat_key = (event_key, heat_number)
            self.event_drivers_per_heat[heat_key] = driver_cids
            
            # Calculate union of all heats for this event
            all_drivers_in_event = set()
            for (ek, hn), cids in self.event_drivers_per_heat.items():
                if ek == event_key:
                    all_drivers_in_event.update(cids)
            
            # Get existing drivers from database
            existing_cids = self.event_drivers.get(event_key, set())
            
            # Check if driver list changed
            driver_list_changed = False
            if all_drivers_in_event != existing_cids:
                new_cids = all_drivers_in_event - existing_cids
                removed_cids = existing_cids - all_drivers_in_event
                
                print(f"\nCurrent: {group_name} | {run_name} (heat {heat_number}) ({len(driver_cids)} drivers in this heat)")
                if len(new_cids) > 0:
                    print(f"  +{len(new_cids)} new driver(s) to event")
                if len(removed_cids) > 0:
                    print(f"  -{len(removed_cids)} removed driver(s) from event")
                
                driver_list_changed = True
            else:
                new_cids = set()
                removed_cids = set()
            
            # Update database (handles additions, removals, and info updates)
            self._update_database(event_key, event_name, group_name, drivers, existing_cids, 
                                all_drivers_in_event, removed_cids, driver_cids, driver_list_changed)

            # Always update timing database when XML changes
            if heat_number > 0:
                self._update_timing_database(event_key, heat_number, result_list)
            
            # CRITICAL: Always update cache to match reality (even if driver list didn't change)
            # This prevents cache from getting out of sync with database
            self.event_drivers[event_key] = all_drivers_in_event
            self.last_event_drivers[event_key] = all_drivers_in_event
            
            return True
        
        except Exception as e:
            print(f"Error processing current.xml: {e}")
            traceback.print_exc()
            return False
    
    def _update_online_scdb(self, event_key: str, heat_number: int):
        """Update Online.scdb with current active event and heat"""
        try:
            if event_key not in self.event_db_mapping:
                return
            
            db_filename = self.event_db_mapping[event_key]
            # Extract event number (e.g., "042" from "Event042.scdb")
            event_num = db_filename.replace("Event", "").replace(".scdb", "")
            
            online_path = os.path.join(self.intermediate_dir, "Online.scdb")
            
            with sqlite3.connect(online_path) as conn:
                cursor = conn.cursor()
                
                # Create TPARAMETERS table if not exists
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS TPARAMETERS (
                        C_PARAM CHAR(32) NOT NULL,
                        C_VALUE VARCHAR(510),
                        PRIMARY KEY(C_PARAM)
                    );
                """)
                
                # Update EVENT and HEAT parameters
                cursor.execute("INSERT OR REPLACE INTO TPARAMETERS (C_PARAM, C_VALUE) VALUES ('EVENT', ?);", (event_num,))
                cursor.execute("INSERT OR REPLACE INTO TPARAMETERS (C_PARAM, C_VALUE) VALUES ('HEAT', ?);", (str(heat_number),))
                
                conn.commit()
                
                # Update internal state
                self.active_state["event"] = event_num.zfill(3)
                self.active_state["heat"] = heat_number
                
                print(f"  Online.scdb updated: EVENT={event_num}, HEAT={heat_number}")
        
        except Exception as e:
            print(f"Error updating Online.scdb: {e}")
            traceback.print_exc()
    
    def _get_heat_number(self, event_key: str, run_name: str) -> int:
        """Determine heat number based on run order in schedule (sorted by datetime)"""
        if event_key not in self.schedule:
            return 0
        
        runs = self.schedule[event_key].get("runs", [])
        
        try:
            # Heat number is 1-indexed position in runs list (already sorted by datetime)
            heat_num = runs.index(run_name) + 1
            return heat_num
        except ValueError:
            # Run not found in schedule
            return 0
    
    def _update_timing_database(self, event_key: str, heat_number: int, result_list: list):
        """Update EventXex.scdb with timing data"""
        try:
            # Get the base Event database filename
            if event_key not in self.event_db_mapping:
                return
            
            db_filename = self.event_db_mapping[event_key]
            # Create Ex version (e.g., Event042.scdb -> Event042Ex.scdb)
            ex_filename = db_filename.replace(".scdb", "Ex.scdb")
            ex_path = os.path.join(self.intermediate_dir, ex_filename)
            
            with sqlite3.connect(ex_path) as conn:
                cursor = conn.cursor()
                
                # Create timing tables for this heat
                info_table = f"TTIMEINFOS_HEAT{heat_number}"
                startlist_table = f"TSTARTLIST_HEAT{heat_number}"
                
                # Create startlist table
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {startlist_table} (
                        C_NUM INTEGER PRIMARY KEY
                    );
                """)
                
                # Create timing info table with C_DATA2
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {info_table} (
                        C_NUM INTEGER PRIMARY KEY,
                        C_INTER1 INTEGER,
                        C_INTER2 INTEGER,
                        C_INTER3 INTEGER,
                        C_SPEED1 INTEGER,
                        C_STATUS INTEGER,
                        C_TIME INTEGER,
                        C_DATA2 INTEGER
                    );
                """)
                
                # Update timing data for each driver
                drivers_updated = 0
                for result in result_list:
                    cid = str(result.get("no", ""))
                    if not cid:
                        continue
                    
                    # Extract total time (convert to milliseconds)
                    totaltime_str = result.get("totaltime", "0")
                    try:
                        # Skip if empty or dash
                        if not totaltime_str or totaltime_str == "-" or totaltime_str == "":
                            totaltime_ms = 0
                        elif ":" in totaltime_str:
                            # Format like "1:09.123" -> convert to ms
                            parts = totaltime_str.split(":")
                            minutes = int(parts[0])
                            seconds = float(parts[1])
                            totaltime_ms = int((minutes * 60 + seconds) * 1000)
                        else:
                            # Format like "20.824" -> convert to ms
                            totaltime_ms = int(float(totaltime_str) * 1000)
                    except:
                        totaltime_ms = 0
                    
                    # Insert/update startlist
                    cursor.execute(f"""
                        INSERT OR REPLACE INTO {startlist_table} (C_NUM)
                        VALUES (?);
                    """, (cid,))
                    
                    # Insert/update timing info (C_DATA2 = C_TIME)
                    cursor.execute(f"""
                        INSERT OR REPLACE INTO {info_table} 
                        (C_NUM, C_INTER1, C_INTER2, C_INTER3, C_SPEED1, C_STATUS, C_TIME, C_DATA2)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                    """, (cid, 0, 0, 0, 0, 0, totaltime_ms, totaltime_ms))
                    
                    drivers_updated += 1
                
                conn.commit()
                requests.get(f"http://{self.host}:7777/api/active_event_update", timeout=1)
                print(f"  Timing: heat {heat_number}, {drivers_updated} driver(s) updated")
        
        except Exception as e:
            print(f"Error updating timing database: {e}")
            traceback.print_exc()
    
    def _update_database(self, event_key: str, event_name: str, group_name: str, drivers: Dict, 
                        existing_cids: Set, all_driver_cids: Set, removed_cids: Set, 
                        current_heat_cids: Set, driver_list_changed: bool):
        """Update event database - always update info for drivers in current heat"""
        try:
            # Get or create database file
            if event_key not in self.event_db_mapping:
                existing_files = os.listdir(self.intermediate_dir)
                for num in range(32, 999):
                    db_filename = f"Event{str(num).zfill(3)}.scdb"
                    if db_filename not in existing_files:
                        self.event_db_mapping[event_key] = db_filename
                        break
            
            db_filename = self.event_db_mapping[event_key]
            db_path = os.path.join(self.intermediate_dir, db_filename)
            
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                
                # Create tables
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS TPARAMETERS (
                        C_PARAM CHAR(32) NOT NULL,
                        C_VALUE VARCHAR(510),
                        PRIMARY KEY(C_PARAM)
                    );
                """)
                
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS TCOMPETITORS (
                        C_IDX INTEGER NOT NULL,
                        C_NUM INTEGER,
                        C_FIRST_NAME VARCHAR(60),
                        C_LAST_NAME VARCHAR(60),
                        C_CLUB VARCHAR(60),
                        C_TEAM VARCHAR(60),
                        PRIMARY KEY(C_IDX)
                    );
                """)
                
                # Update parameters
                heats = self.schedule.get(event_key, {}).get("heats", 1)
                cursor.execute("INSERT OR REPLACE INTO TPARAMETERS (C_PARAM, C_VALUE) VALUES ('TITLE1', ?);", (event_name,))
                cursor.execute("INSERT OR REPLACE INTO TPARAMETERS (C_PARAM, C_VALUE) VALUES ('TITLE2', ?);", (group_name,))
                cursor.execute("INSERT OR REPLACE INTO TPARAMETERS (C_PARAM, C_VALUE) VALUES ('MODULE', '0');")
                cursor.execute("INSERT OR REPLACE INTO TPARAMETERS (C_PARAM, C_VALUE) VALUES ('DATE', ?);", (str(int(time.time())),))
                cursor.execute("INSERT OR REPLACE INTO TPARAMETERS (C_PARAM, C_VALUE) VALUES ('HEAT_NUMBER', ?);", (str(heats),))
                
                # Only do removals/additions if list changed
                if driver_list_changed:
                    # Remove drivers no longer in event
                    for cid in removed_cids:
                        cursor.execute("DELETE FROM TCOMPETITORS WHERE C_NUM = ?;", (cid,))
                        print(f"  Removed driver {cid}")
                    
                    # Add new drivers (only those in current heat will have full info)
                    new_cids = all_driver_cids - existing_cids
                    
                    if len(new_cids) > 0:
                        # Double-check against actual database to prevent duplicates
                        cursor.execute("SELECT C_NUM FROM TCOMPETITORS;")
                        db_cids = {str(row[0]) for row in cursor.fetchall()}
                        actually_new_cids = new_cids - db_cids
                        
                        if len(actually_new_cids) < len(new_cids):
                            print(f"  Warning: Cache mismatch detected, prevented {len(new_cids - actually_new_cids)} duplicate(s)")
                        
                        if len(actually_new_cids) > 0:
                            cursor.execute("SELECT MAX(C_IDX) FROM TCOMPETITORS;")
                            max_idx = cursor.fetchone()[0]
                            next_idx = (max_idx + 1) if max_idx is not None else 1
                            
                            for cid in actually_new_cids:
                                # Only add with full info if in current heat, otherwise add placeholder
                                if cid in current_heat_cids:
                                    d = drivers.get(cid, {"cid": cid, "first_name": "", "last_name": "", "club": "", "team": ""})
                                else:
                                    # Driver from another heat - add with empty info for now
                                    d = {"cid": cid, "first_name": "", "last_name": "", "club": "", "team": ""}
                                
                                cursor.execute("""
                                    INSERT INTO TCOMPETITORS (C_IDX, C_NUM, C_FIRST_NAME, C_LAST_NAME, C_CLUB, C_TEAM)
                                    VALUES (?, ?, ?, ?, ?, ?);
                                """, (next_idx, cid, d["first_name"], d["last_name"], d["club"], d["team"]))
                                next_idx += 1
                
                # ALWAYS update drivers in current heat (even if list didn't change)
                # This ensures placeholders get filled in when their heat is processed
                updated_count = 0
                for cid in current_heat_cids:
                    d = drivers.get(cid)
                    if d and (d["first_name"] or d["last_name"]):  # Only update if we have at least a name
                        cursor.execute("""
                            UPDATE TCOMPETITORS 
                            SET C_FIRST_NAME = ?, C_LAST_NAME = ?, C_CLUB = ?, C_TEAM = ?
                            WHERE C_NUM = ?;
                        """, (d["first_name"], d["last_name"], d["club"], d["team"], cid))
                        updated_count += 1
                
                if updated_count > 0 and not driver_list_changed:
                    print(f"  Updated info for {updated_count} driver(s)")
                
                conn.commit()
        
        except Exception as e:
            print(f"Error updating database: {e}")
            traceback.print_exc()
    
    def handle_scdb_file(self, file_path: str):
        """Handle .scdb file updates"""
        dest_path = os.path.join(self.intermediate_dir, os.path.basename(file_path))
        
        try:
            shutil.copy2(file_path, dest_path)
            
            filename = os.path.basename(file_path)
            
            if "Online.scdb" in filename:
                self._handle_online_scdb(dest_path)
            elif "Event" in filename and "Ex" in filename and filename.endswith("Ex.scdb"):
                self._handle_event_ex_scdb(dest_path)
        
        except Exception as e:
            print(f"Error handling {file_path}: {e}")
    
    def _handle_online_scdb(self, db_path: str):
        """Handle Online.scdb"""
        try:
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(ACTIVE_EVENT_QUERY)
                active_data = cursor.fetchall()
                
                if len(active_data) >= 2:
                    event = active_data[0][0]
                    heat = active_data[1][0]
                    
                    requests.get(f"http://{self.host}:7777/api/active_event_update", timeout=2)
                    
                    self.active_state["heat"] = heat
                    
                    if event.zfill(3) != self.active_state["event"]:
                        self.active_state["event"] = event.zfill(3)
                        
                        event_db_path = os.path.join(self.intermediate_dir, f"Event{self.active_state['event']}.scdb")
                        
                        if os.path.exists(event_db_path):
                            with sqlite3.connect(event_db_path) as event_conn:
                                cursor = event_conn.cursor()
                                cursor.execute(MODE_QUERY)
                                mode = cursor.fetchall()[0][0]
                                self.active_state["mode"] = mode
        except:
            pass
    
    def _handle_event_ex_scdb(self, db_path: str):
        """Handle EventXEx.scdb timing files"""
        try:
            filename = os.path.basename(db_path)
            event_num = filename.replace("Event", "").replace("Ex.scdb", "")
            
            if event_num != self.active_state["event"]:
                return
            
            mode = self.active_state["mode"]
            
            if int(mode) == 3:
                total_heat_query = "SELECT C_VALUE FROM TPARAMETERS WHERE C_PARAM = 'HEAT_NUMBER'"
                event_db_path = os.path.join(self.intermediate_dir, f"Event{self.active_state['event']}.scdb")
                
                with sqlite3.connect(event_db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute(total_heat_query)
                    total_heat = int(cursor.fetchall()[0][0])
                    curr_count = (total_heat - int(self.active_state["heat"])) + 1
                
                query = f"SELECT C_NUM, C_INTER1, C_INTER2, C_INTER3, C_SPEED1, C_STATUS, C_TIME FROM TTIMEINFOS_PARF_HEAT{curr_count}_RUN1"
            else:
                query = f"SELECT C_NUM, C_INTER1, C_INTER2, C_INTER3, C_SPEED1, C_STATUS, C_TIME FROM TTIMEINFOS_HEAT{self.active_state['heat']}"
            
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                time_data = cursor.fetchall()
                
                self.startlist_dict = []
                send_update = True
                
                for row in time_data:
                    cid = row[0]
                    if all(x == 0 for x in row[1:]):
                        self.startlist_dict.append({"CID": cid, "STATUS": "STARTED"})
                        send_update = False
                    else:
                        self.startlist_dict.append({"CID": cid, "STATUS": "FINISHED"})
                
                if int(mode) == 0:
                    requests.get(f"http://{self.host}:7777/api/active_event_update", timeout=2)
                else:
                    if send_update:
                        requests.get(f"http://{self.host}:7777/api/active_event_update", timeout=2)
                
                url = f"http://{self.host}:7777/api/start_status"
                headers = {'Content-Type': 'application/json'}
                requests.post(url, json=self.startlist_dict, headers=headers, timeout=2)
        except:
            pass
    
    def run(self, interval: int = 3):
        """Main monitoring loop"""
        print(f"Monitoring {self.source_dir}")
        
        try:
            while True:
                files = [item.path for item in os.scandir(self.source_dir) if item.is_file()]
                
                for file_path in files:
                    if file_path not in self.last_modified_times:
                        self.last_modified_times[file_path] = None
                
                for file_path in files:
                    try:
                        current_mtime = os.path.getmtime(file_path)
                    except FileNotFoundError:
                        continue
                    
                    filename = os.path.basename(file_path)
                    
                    if self.last_modified_times[file_path] is None or current_mtime > self.last_modified_times[file_path]:
                        
                        if filename == 'schedule.xml':
                            if self.parse_schedule(file_path):
                                print("Schedule updated")
                            self.last_modified_times[file_path] = current_mtime
                        
                        elif filename == 'current.xml':
                            if self.schedule:
                                self.process_current(file_path)
                            self.last_modified_times[file_path] = current_mtime
                        
                        elif filename.endswith('.scdb'):
                            self.handle_scdb_file(file_path)
                            self.last_modified_times[file_path] = current_mtime
                
                time.sleep(interval)
        
        except KeyboardInterrupt:
            print("\nStopped by user")
        except Exception as e:
            print(f"Fatal error: {e}")
            traceback.print_exc()


def main():
    try:
        with sqlite3.connect("site.db") as con:
            cur = con.cursor()
            host = cur.execute("SELECT params FROM microservices WHERE path = 'msport_display_proxy.py';").fetchone()[0]
            if str(host) == "0.0.0.0":
                host = "localhost"
    except:
        host = "localhost"
    
    source_directory = '/mnt/test'
    intermediate_directory = '/mnt/intermediate'
    
    monitor = FileMonitor(source_directory, intermediate_directory, host)
    monitor.run(interval=0.5)


if __name__ == "__main__":
    main()