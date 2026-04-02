import subprocess
import logging
import signal
import sys
import sqlite3
import requests
import psutil
import os
import select
from threading import Thread
from flask import current_app
import json

def get_event_meta():
    from app.models import ActiveDrivers, Session_Race_Records, ActiveEvents

    active_drivers = ActiveDrivers.query.first()
    event_id = active_drivers.Event_id

    active_event_row = ActiveEvents.query.filter(ActiveEvents.event_checksum == event_id).first()
    heat = active_event_row.run if active_event_row else active_drivers.Heat

    event_data = Session_Race_Records.query.filter(Session_Race_Records.event_id == event_id).first()

    if event_data is None:
        return {"TITLE_1": "", "TITLE_2": "", "HEAT": heat, "HEATS": 1, "EVENT_TYPE": ""}

    title_1 = event_data.title_1
    title_2 = event_data.title_2
    heats = event_data.data.get("heats", 1) if event_data.data else 1

    if "Kvali".lower() in title_2.lower():
        event_type = "Kvalifisering"
        title_2 = title_2.removesuffix(" - Kvalifisering")
    elif "Finale".lower() in title_2.lower():
        event_type = "Finale"
        title_2 = title_2.removesuffix(" - Finale")
    elif "Stige".lower() in title_2.lower():
        title_2 = title_2.removesuffix(" - Stige")
        event_type = "Stige"
    else:
        event_type = ""
    
    return {"TITLE_1":title_1, "TITLE_2":title_2, "HEAT":heat, "HEATS":heats, "EVENT_TYPE":event_type}

def extract_class(name: str) -> str:
    import re
    """Extract the base class name (e.g., '600 Stock') from a full event name."""
    # Remove known suffixes: Finale, Kvalifisering, C Finale, B Finale, A Finale, Heat, etc.
    suffixes = r'\s*[-–]\s*(A|B|C|D)?\s*(Finale|Kvalifisering|Heat|Semi|Semifinale)\w*$'
    return re.sub(suffixes, '', name, flags=re.IGNORECASE).strip()

def combine_qualifying_results(
    results,
    tiebreakers: list[str] = ["combined_finishtime"]
):
    INVALID_STATUSES = {'DNF', 'DSQ', 'DNS'}
    VALID_TIEBREAKERS = {"combined_finishtime", "lowest_finishtime", "best_lap_time", "laps"}

    from app.models import StandingConfig
    mix_classes = bool(StandingConfig.query.first().mix_classes)

    for tb in tiebreakers:
        if tb not in VALID_TIEBREAKERS:
            raise ValueError(f"Invalid tiebreaker '{tb}'. Must be one of: {VALID_TIEBREAKERS}")
    if len(tiebreakers) != len(set(tiebreakers)):
        raise ValueError("Tiebreakers list cannot contain duplicates.")
    if len(tiebreakers) > 2:
        raise ValueError("Maximum 2 tiebreakers allowed (primary and secondary).")

    def parse_time(value):
        value = str(value).strip()
        if ':' in value:
            parts = value.split(':')
            return int(parts[0]) * 60 + float(parts[1])
        return float(value)

    def format_time(seconds):
        if seconds >= 60:
            minutes = int(seconds // 60)
            secs = seconds % 60
            return f"{minutes}:{secs:06.3f}"
        return f"{round(seconds, 3):.3f}"

    def build_drivers(entries):
        drivers = {}
        total_heats = 0

        for entry in entries:
            cid = entry['cid']
            heat_num = int(entry['heat'])

            if heat_num > total_heats:
                total_heats = heat_num

            if cid not in drivers:
                drivers[cid] = {
                    'cid': cid,
                    'first_name': entry['first_name'],
                    'last_name': entry['last_name'],
                    'club': entry['club'],
                    'class': entry['class'],
                    'run_name': entry['run_name'],
                    'heats': {}
                }
            else:
                if entry['first_name'] != entry['last_name']:
                    drivers[cid]['first_name'] = entry['first_name']
                    drivers[cid]['last_name'] = entry['last_name']

            position = entry['position']
            time_value = position if position in INVALID_STATUSES else parse_time(entry['totaltime'])
            best_lap = parse_time(entry['best_time']) if entry.get('best_time') and entry['best_time'] not in INVALID_STATUSES else None

            drivers[cid]['heats'][heat_num] = {
                'totaltime': time_value,
                'points': entry['points'],
                'position': position,
                'best_lap': best_lap,
                'laps': int(entry.get('laps', 0)),
            }

        return drivers, total_heats

    def build_combined(drivers, total_heats):
        combined = []

        for cid, driver in drivers.items():
            row = {
                'cid': cid,
                'first_name': driver['first_name'],
                'last_name': driver['last_name'],
                'club': driver['club'],
                'class': driver['class'],
            }

            total_points = 0
            valid_times = []
            best_laps = []
            total_laps = 0

            for h in range(1, total_heats + 1):
                time_key = f'R{h}'
                points_key = f'R{h}_POINTS'

                if h in driver['heats']:
                    heat = driver['heats'][h]
                    t = heat['totaltime']
                    pts = heat['points']
                    total_points += pts
                    total_laps += heat['laps']

                    row[time_key] = format_time(t) if isinstance(t, float) else t
                    row[points_key] = pts

                    if isinstance(t, float):
                        valid_times.append(t)
                    if heat['best_lap'] is not None:
                        best_laps.append(heat['best_lap'])
                else:
                    row[time_key] = "0.000"
                    row[points_key] = 0

            combined_secs = sum(valid_times)
            lowest_secs = min(valid_times) if valid_times else 0
            best_lap_secs = min(best_laps) if best_laps else None

            row['combined_points'] = total_points
            row['combined_finishtime'] = format_time(combined_secs) if combined_secs > 0 else "0.000"
            row['lowest_finishtime'] = format_time(lowest_secs) if lowest_secs > 0 else "0.000"
            row['best_lap_time'] = format_time(best_lap_secs) if best_lap_secs is not None else "0.000"
            row['total_laps'] = total_laps

            row['_sort_combined'] = combined_secs
            row['_sort_lowest'] = lowest_secs
            row['_sort_best_lap'] = best_lap_secs if best_lap_secs is not None else float('inf')
            row['_sort_laps'] = total_laps
            row['_sort_points'] = total_points

            combined.append(row)

        return combined

    def get_sort_value(row, criterion):
        if criterion == "combined_finishtime":
            return row['_sort_combined'] if row['_sort_combined'] > 0 else float('inf')
        elif criterion == "lowest_finishtime":
            return row['_sort_lowest'] if row['_sort_lowest'] > 0 else float('inf')
        elif criterion == "best_lap_time":
            return row['_sort_best_lap']
        elif criterion == "laps":
            return -row['_sort_laps']  # More laps = better, so negate

    def make_sort_key(row):
        # Points always primary, tiebreakers applied in order after
        key = [-row['_sort_points']]
        for tb in tiebreakers:
            key.append(get_sort_value(row, tb))
        return tuple(key)

    def assign_standings(combined, mix_classes):
        if mix_classes:
            combined.sort(key=make_sort_key)
            for i, row in enumerate(combined):
                row['internal_standing'] = i + 1
        else:
            class_groups = {}
            for row in combined:
                class_groups.setdefault(row['class'], []).append(row)

            combined.clear()
            for cls, group in class_groups.items():
                group.sort(key=make_sort_key)
                for i, row in enumerate(group):
                    row['internal_standing'] = i + 1
                combined.extend(group)

        for row in combined:
            for key in ['_sort_combined', '_sort_lowest', '_sort_best_lap', '_sort_laps', '_sort_points']:
                del row[key]

        return combined

    # --- Main ---
    run_name = results[0]['run_name'] if results else ''
    unique_classes = set(entry['class'] for entry in results)
    has_multiple_classes = len(unique_classes) > 1

    drivers, total_heats = build_drivers(results)
    combined = build_combined(drivers, total_heats)
    combined = assign_standings(combined, mix_classes)

    return {
        'meta': {
            'run_name': run_name,
            'mix_classes': mix_classes,
            'has_multiple_classes': has_multiple_classes,
            'tiebreakers': tiebreakers,
        },
        'results': combined
    }

def calculate_standing_msport(records):
    """
    Calculate standings from msport Session_Race_Records data (data JSON blobs).

    records: list of dicts (each is a Session_Race_Records.data JSON blob).

    Ranking rules (module "2" = kvalifisering):
      - Primary: best clean finishtime across all heats (ascending, lower = better)
      - Penalized with no clean time → placed after all clean finishes
      - No finishtime at all → placed last
      - Drivers with cid 11111 (FILLER) are excluded

    Returns dict:
      {
        'meta': { 'title_2': str, 'total_heats': int, 'tiebreaker': 'lowest_finishtime' },
        'results': [
          {
            'cid', 'first_name', 'last_name', 'club', 'snowmobile',
            'R{n}', 'R{n}_penalty',   # per heat: finishtime (ms) or 0
            'lowest_finishtime',       # best clean time in ms, 0 if none
            'combined_finishtime',     # sum of all clean times in ms
            'internal_standing',       # 1-based position (ties share same position)
            'points',                  # from StandingConfig.driver_scores
          }, ...
        ]
      }
    """
    from app.models import StandingConfig

    standing_config = StandingConfig.query.first()
    use_points      = standing_config.use_points if standing_config else False
    driver_scores   = standing_config.driver_scores if standing_config else {}
    dns_point       = standing_config.dns_point if standing_config else 0

    FILLER_CID = 11111

    # Group records by cid
    drivers = {}
    total_heats = 0
    title_2 = ""

    for entry in records:
        cid = entry.get("cid")
        if cid is None or cid == FILLER_CID:
            continue

        heat_num = int(entry.get("heat", 1))
        total_heats = max(total_heats, heat_num)
        title_2 = entry.get("title_2", title_2)

        if cid not in drivers:
            drivers[cid] = {
                "cid":        cid,
                "first_name": entry.get("first_name", ""),
                "last_name":  entry.get("last_name", ""),
                "club":       entry.get("club", ""),
                "snowmobile": entry.get("snowmobile", ""),
                "heats":      {},
            }

        drivers[cid]["heats"][heat_num] = {
            "finishtime": entry.get("finishtime", 0),
            "penalty":    entry.get("penalty", 0),
        }

    # Build result rows
    rows = []
    for cid, driver in drivers.items():
        row = {
            "cid":        cid,
            "first_name": driver["first_name"],
            "last_name":  driver["last_name"],
            "club":       driver["club"],
            "snowmobile": driver["snowmobile"],
        }

        clean_times = []
        for h in range(1, total_heats + 1):
            heat = driver["heats"].get(h, {"finishtime": 0, "penalty": 0})
            ft  = heat["finishtime"]
            pen = heat["penalty"]
            row[f"R{h}"]         = ft
            row[f"R{h}_penalty"] = pen
            if ft and ft > 0 and pen == 0:
                clean_times.append(ft)

        row["lowest_finishtime"]   = min(clean_times) if clean_times else 0
        row["combined_finishtime"] = sum(clean_times) if clean_times else 0
        row["_sort_lowest"]        = row["lowest_finishtime"] if clean_times else float("inf")

        rows.append(row)

    # Sort: fastest lowest_finishtime first; drivers with no clean time last
    rows.sort(key=lambda r: r["_sort_lowest"])

    # Assign positions and points (ties share the same position)
    pos = 0
    prev_sort = None
    for i, row in enumerate(rows):
        sort_val = row["_sort_lowest"]
        if sort_val != prev_sort:
            pos = i + 1
            prev_sort = sort_val

        row["internal_standing"] = pos
        del row["_sort_lowest"]

        if use_points:
            if sort_val == float("inf"):
                row["points"] = dns_point
            else:
                row["points"] = driver_scores.get(str(pos), 0)
        else:
            row["points"] = 0

    return {
        "meta": {
            "title_2":     title_2,
            "total_heats": total_heats,
            "tiebreaker":  "lowest_finishtime",
        },
        "results": rows,
    }


def get_combined_results(event_prefix, kvali=False):
    from app.models import Session_Race_Records
    from app.models import StandingConfig
    
    if kvali:
        data = Session_Race_Records.query.filter(
            Session_Race_Records.title_2.ilike(event_prefix + " - Kvalifisering")).all()
    else:
        data = Session_Race_Records.query.filter(Session_Race_Records.title_2.like(event_prefix)).all()
    data_list = []
    
    for a in data:
        data_list.append(a.data)
    config_tie = StandingConfig.query.first()
    print(config_tie.scoring_method)
    if config_tie.scoring_method == "best_lap":
        tie_b = ["lowest_finishtime"]
    else:
        tie_b = ["lowest_finishtime"]

    data = combine_qualifying_results(data_list, tiebreakers=tie_b)
    data["meta"]["scoring_method"] = config_tie.scoring_method

    return data



def get_dash_data():
    from app.models import Session_Race_Records, ActiveDrivers, GlobalConfig
    from sqlalchemy import cast, String
    
    race_type = GlobalConfig.query.first().race_type
    
    
    if int(race_type) == 5:
        active_event = ActiveDrivers.query.first().Event_id
        events_data = Session_Race_Records.query.filter(Session_Race_Records.event_id == active_event).order_by(cast(Session_Race_Records.data['internal_standing'], String)).all()
        data = {}
        
        for k,a in enumerate(events_data):
            k = k + 1
            data_dict = a.data
            data[k] = {
                "mutli_class": data_dict["multi_class"],
                "class": data_dict["class"],
                "cid": data_dict["cid"],
                "first_name": data_dict["first_name"],
                "last_name": data_dict["last_name"],
                "totaltime": data_dict["totaltime"],
                "laps": data_dict["laps"],
                "position": k,
                "penalty": data_dict["penalty"],
                "finished": data_dict["finished"],
                "best_time": data_dict["best_time"],
                "last_lap_time": data_dict["last_lap_time"],
                "points": data_dict["points"]
            }
        return {"event_data":data}

def get_event_results(data_type=None, event_name=None, event_id=None, format=None, index_counter=None):
    from app.models import Session_Race_Records, StandingConfig, ActiveDrivers
    from flask import current_app
    from sqlalchemy import cast, String

    race_type = int(GetEnv()["race_type"])


    if "results" in data_type:

        if race_type == 5:

            active_event = ActiveDrivers.query.first()
            event_id = active_event.Event_id
            results = Session_Race_Records.query.filter(Session_Race_Records.event_id == event_id).order_by(cast(Session_Race_Records.data['internal_standing'], String)).all()
            standing_config = StandingConfig.query.first()

            if len(results) == 0:
                return "NO EVENTS FOUND"
            
            if "kvali" in results[0].title_2.lower() or "quali" in results[0].title_2.lower():
                
                if standing_config.use_points == True:
                    data_set = "ID,Navn,Kjøretøy,Beste Rundetid,Runder,Tid,Poeng\n"
                else:
                    data_set = "ID,Navn,Kjøretøy,Beste Rundetid,Runder,Tid\n"

                for a in results:
                    name = a.data["first_name"] + a.data["last_name"]
                    snowmobile = a.data["snowmobile"] if a.data["snowmobile"] != "" else "-"
                    cid = a.cid
                    best_time = a.data["best_time"]
                    totaltime = a.data["totaltime"]
                    laps = a.data["laps"]
                    points = a.data["points"]
                    data_set += f"{cid},{name},{snowmobile},{best_time},{laps},{totaltime},{points}\n" if standing_config.use_points == True else f"{cid},{name},{snowmobile},{best_time},{laps},{totaltime}\n"
                        
        elif race_type == 3:
            active_event = ActiveDrivers.query.first()
            event_id = active_event.Event_id
            results = Session_Race_Records.query.filter(Session_Race_Records.event_id == event_id).order_by(cast(Session_Race_Records.data['internal_standing'], String)).all()
            standing_config = StandingConfig.query.first()

            if len(results) == 0:
                return "NO EVENTS FOUND"
            
            if "kvali" in results[0].title_2.lower() or "quali" in results[0].title_2.lower():
                
                if standing_config.use_points == True:
                    data_set = "ID,Navn,Kjøretøy,Beste Rundetid,Runder,Tid,Poeng\n"
                else:
                    data_set = "ID,Navn,Kjøretøy,Beste Rundetid,Runder,Tid\n"

                for a in results:
                    name = a.data["first_name"] + a.data["last_name"]
                    snowmobile = a.data["snowmobile"] if a.data["snowmobile"] != "" else "-"
                    cid = a.cid
                    best_time = a.data["best_time"]
                    totaltime = a.data["totaltime"]
                    laps = a.data["laps"]
                    points = a.data["points"]
                    data_set += f"{cid},{name},{snowmobile},{best_time},{laps},{totaltime},{points}\n" if standing_config.use_points == True else f"{cid},{name},{snowmobile},{best_time},{laps},{totaltime}\n"
                        
    return data_set



def find_active_event():
    from app.models import Session_Race_Records

    event = Session_Race_Records.query.filter(Session_Race_Records.active_event==True).first()
    if event == None:
        return ""
    else:
        return event.event_id



def calculate_standing(entries):
    from app.models import StandingConfig
    
    standing_config = StandingConfig.query.first()
    
    scoring_method = standing_config.scoring_method
    dnf = standing_config.dnf_point
    dsq = standing_config.dsq_point
    dns = standing_config.dns_point
    calculate_points = standing_config.use_points
    tiebreaker_method = standing_config.tiebreaker_method
    use_tiebreaker = standing_config.use_tiebreaker

    points = standing_config.driver_scores

    standings = []
    heat_position = 0

    def get_best_time(entry):
        if not entry[5]:
            return float('inf')

        data = json.loads(entry[5])
        best_time = data.get("best_time")

        if best_time is None:
            return float('inf')

        best_time = str(best_time)
        if ":" in best_time:
            parts = best_time.split(":")
            total_seconds = 0
            for index, part in enumerate(parts):
                value = float(part)
                total_seconds += value * 60 if index == 0 else value
            return total_seconds

        return float(best_time)


    def get_total_time(entry):
        if not entry[5]:
            return float('inf')

        data = json.loads(entry[5])
        time_string = data.get("totaltime", "")

        if not time_string:
            return float('inf')

        parts = time_string.split(":")
        total_seconds = 0

        for index, part in enumerate(parts):
            value = float(part)
            if index == 0:
                total_seconds += value * 60
            else:
                total_seconds += value

        return total_seconds

    def get_lap_count(entry):
        if not entry[5]:
            return float('inf')

        data = json.loads(entry[5])
        laps = data.get("laps")

        if laps is None:
            return float('inf')

        return float(laps)
    
    key_map = {
        "best_lap": get_best_time,
        "total_time": get_total_time,
        "num_rounds": get_lap_count,
    }

    primary_key = key_map[scoring_method]

    if use_tiebreaker:
        secondary_key = key_map[tiebreaker_method]

        def sort_key(e):
            primary = primary_key(e)
            secondary = secondary_key(e)

            # Make laps descending by negating
            if scoring_method == "num_rounds":
                primary = -primary

            return (primary, secondary)

    else:
        def sort_key(e):
            value = primary_key(e)
            if scoring_method == "num_rounds":
                value = -value
            return value

    sorted_entries = sorted(entries, key=sort_key)

    for a in sorted_entries:
        data = json.loads(a[5])
        
        if "D" not in str(data.get("position", "")) and bool(data["finished"]) == True:
            heat_position += 1
            post = heat_position
            if calculate_points:
                point = points.get(str(post), 0)
            else:
                point = 0
            
        else:
            if "dns".upper() in str(data.get("position", "")):
                point = dns
            elif "dnf".upper() in str(data.get("position", "")):
                point = dnf
            elif "dq".upper() in str(data.get("position", "")).upper() or "dsq".upper() in str(data.get("position", "")).upper():
                point = dsq
            else:
                point = 0

            post = 99
        cid = a[0]
        standings.append([cid, [post, point]])
    
    return standings
    
        
def insert_event_data(event_id=None, full_sync=None, active=None):
    from app.lib.db_func import insert_orbits_data, insert_msports_data
    print(full_sync)
    g_config = GetEnv()
    if g_config["msport_tm"] == False:
        if event_id != None:
            insert_orbits_data(event_id=event_id)
        elif full_sync != None:
            insert_orbits_data(full_sync=True)
        elif active != None:
            insert_orbits_data(active_only=True)
    else:
        if event_id != None:
            insert_msports_data(event_id=event_id)
        elif full_sync != None:
            insert_msports_data(full_sync=True)
        elif active != None:
            insert_msports_data(active=True, lookup_active=True)
            

def get_upcoming_drivers(return_driver_context=False):
    from app.lib.db_operation import (
        get_active_startlist_w_timedate,
        get_active_startlist,
    )

    with sqlite3.connect("site.db") as con:
        query = "SELECT D1, D2 FROM active_drivers;"
        cur = con.cursor()
        active_driver = cur.execute(query).fetchall()
        D1 = active_driver[0][0]
        D2 = active_driver[0][1]

    current_event_data = get_active_startlist_w_timedate()

    next_event = False
    next_drivers = False

    race_config = current_event_data[0]["race_config"]
    mode = race_config.get("MODE", 0)
    # mode 2 = kvalifisering (two drivers side-by-side, lane order by best kvali time)
    # mode 1 = finale/single (one driver per race slot)
    is_kvali = (mode == 2)

    def _build_driver_data(race_entry, event_config, use_kvali):
        drivers = race_entry["drivers"]
        D1_id = drivers[0]["id"]
        D2_id = drivers[1]["id"] if len(drivers) > 1 else 0

        if use_kvali:
            best_time = get_best_kvali_time({"D1": D1_id, "D2": D2_id}, event_config["TITLE_2"])
            if best_time.index(D1_id) == 0:
                result = {"D1": [D1_id, "green"], "D2": [D2_id, "white"]}
            else:
                result = {"D1": [D1_id, "white"], "D2": [D2_id, "green"]}
        else:
            result = {"D1": [D1_id, "white"], "D2": [D2_id, "white"]}

        if return_driver_context:
            result["D1"].append(drivers[0]["first_name"] + " " + drivers[0]["last_name"])
            result["D2"].append(drivers[1]["first_name"] + " " + drivers[1]["last_name"] if len(drivers) > 1 else "")
            result["EVENT_NAME"] = event_config["TITLE_2"]

        return result

    for k, a in enumerate(current_event_data):
        if next_drivers:
            data = _build_driver_data(a, race_config, is_kvali)
            break

        if "race_config" in a:
            continue

        driver_ids = [d["id"] for d in a["drivers"]]
        if D1 in driver_ids or D2 in driver_ids:
            if len(current_event_data) == k + 1:
                next_event = True
            else:
                next_drivers = True

    if next_event:
        nxt_event = get_active_startlist_w_timedate(upcoming=True)

        if len(nxt_event) <= 1:
            return {"D1": ["X", "green"], "D2": ["X", "green"]}

        nxt_config = nxt_event[0]["race_config"]
        nxt_mode = nxt_config.get("MODE", 0)
        nxt_is_kvali = (nxt_mode == 2)

        data = _build_driver_data(nxt_event[1], nxt_config, nxt_is_kvali)

    return data


def get_best_kvali_time(drivers, event):
    from app.models import Session_Race_Records
    from sqlalchemy import or_

    records = (
        Session_Race_Records.query
        .filter(
            Session_Race_Records.title_2 == event,
            or_(
                Session_Race_Records.cid == drivers["D1"],
                Session_Race_Records.cid == drivers["D2"],
            ),
        )
        .all()
    )

    driver_best_time = {drivers["D1"]: 999999999999, drivers["D2"]: 999999999999}

    for rec in records:
        d = rec.data or {}
        finishtime = d.get("finishtime", 0)
        penalty = d.get("penalty", 0)
        if not finishtime:
            continue
        cid = rec.cid
        if cid in driver_best_time:
            if penalty == 0 and finishtime < driver_best_time[cid]:
                driver_best_time[cid] = finishtime

    if driver_best_time[drivers["D1"]] >= driver_best_time[drivers["D2"]]:
        return [
            drivers["D2"],
            driver_best_time[drivers["D2"]],
            drivers["D1"],
            driver_best_time[drivers["D1"]],
        ]
    else:
        return [
            drivers["D1"],
            driver_best_time[drivers["D1"]],
            drivers["D2"],
            driver_best_time[drivers["D2"]],
        ]


def object_to_dict(obj):
    return {
        attr: getattr(obj, attr)
        for attr in dir(obj)
        if not attr.startswith("_") and not callable(getattr(obj, attr))
    }


def Check_Event(event):
    from app.models import ActiveEvents
    from app import db as my_db

    event_query = ActiveEvents.query.filter(
        ActiveEvents.event_file.like(event[0]["db_file"][-15:].replace(".sqlite", ""))
    ).all()
    if len(event_query) == 0:
        return False
    else:
        return True


def Get_active_drivers(g_config, event_data_dict):
    with sqlite3.connect(g_config["project_dir"] + "site.db") as conn:
        cursor = conn.cursor()
        if event_data_dict["MODE"] == 3 or event_data_dict["MODE"] == 2:
            active_drivers_sql = cursor.execute(
                "SELECT D1, D2 FROM active_drivers"
            ).fetchall()
            active_drivers = {
                "D1": active_drivers_sql[0][0],
                "D2": active_drivers_sql[0][1],
            }
        else:
            active_drivers_sql = cursor.execute(
                "SELECT D1 FROM active_drivers"
            ).fetchall()
            active_drivers = {"D1": active_drivers_sql[0][0]}

    return active_drivers


def Set_active_driver(cid_1=False, cod_2=False):
    DB_PATH = "site.db"

    query = "UPDATE active_drivers SET D1 = {0};".format(str(cid_1))

    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute(query)


def export_events(event_file=None):
    from app.models import ActiveEvents
    from app.lib.db_operation import get_active_startlist_w_timedate
    g_config = GetEnv()

    events = ActiveEvents.query.order_by(ActiveEvents.sort_order).all()
    if event_file != None:
        events = (
            ActiveEvents.query.filter(ActiveEvents.event_file == event_file)
            .order_by(ActiveEvents.sort_order)
            .all()
        )
    else:
        events = ActiveEvents.query.order_by(ActiveEvents.sort_order).all()

    data = []
    for a in events:
        event = [
            {
                "db_file": g_config["db_location"] + str(a.event_file) + ".sqlite",
                "SPESIFIC_HEAT": a.run,
            }
        ]

        data.append(get_active_startlist_w_timedate(event=a.event_name, heat=a.run))
        #data.append(format_startlist(event, True))

    return data


def convert_microseconds_to_time(microseconds):
    # convert microseconds to seconds
    seconds = microseconds / 1_000_000

    # calculate each unit and the remainder
    hours, rem = divmod(seconds, 3600)
    minutes, rem = divmod(rem, 60)
    seconds, rem = divmod(rem, 1)
    milliseconds = rem * 1000

    # return a string in the format "hours:minutes:seconds.milliseconds"
    return "{:02d}:{:02d}:{:02d}.{:03d}".format(
        int(hours), int(minutes), int(seconds), int(milliseconds)
    )


def update_info_screen(id):
    from app import db
    from app.models import (
        InfoScreenAssetAssociations,
        InfoScreenAssets,
        InfoScreenInitMessage,
    )

    assets = InfoScreenAssetAssociations.query.filter_by(infoscreen=id)
    infoscreen_url = InfoScreenInitMessage.query.filter_by(id=id).first()
    port = "8000"
    infoscreen_url = f"http://{infoscreen_url.ip}:{port}/update_index"
    json_data = []

    for a in assets:
        entry = {}
        asset_name = InfoScreenAssets.query.filter_by(id=a.asset).first()
        entry = {"name": asset_name.name, "url": asset_name.asset, "timer": a.timer}
        json_data.append(entry)

    requests.post(infoscreen_url, json=json_data)


def GetEnv():
    from app.models import GlobalConfig

    global_config = GlobalConfig.query.all()

    if not global_config:
        return {}

    first_row = global_config[0]
    row_dict = {
        key: value
        for key, value in first_row.__dict__.items()
        if not key.startswith("_")
    }
    if row_dict["use_intermediate"] == True:
        row_dict["event_dir"] = row_dict["intermediate_path"]

    return row_dict


def is_screen_session_running(session_name: str) -> bool:
    """Check if a Screen session with the given name is running."""
    try:
        # Command to list all Screen sessions
        list_sessions_cmd = "screen -ls"
        # Execute the command and decode the output
        sessions_output = subprocess.check_output(
            list_sessions_cmd, shell=True
        ).decode()
        # Check if the session name is in the output
        return session_name in sessions_output
    except subprocess.CalledProcessError:
        # If the screen command fails, assume the session is not running
        return False


def manage_process_screen(
    python_program_path: str, operation: str, new_argument: str = None
) -> None:
    from app.models import GlobalConfig
    import time, subprocess, shlex, logging

    global_config = GlobalConfig.query.get(1)
    program_file = python_program_path
    python_program_path = global_config.project_dir + "scripts/" + python_program_path
    python_executable = sys.executable
    program_name = os.path.basename(python_program_path)
    screen_session_name = f"session_{program_name}"

    def is_screen_session_running(session_name: str) -> bool:
        """Check if a Screen session with the given name is running."""
        try:
            list_sessions_cmd = "screen -ls"
            sessions_output = subprocess.check_output(
                list_sessions_cmd, shell=True
            ).decode()
            return session_name in sessions_output
        except subprocess.CalledProcessError:
            return False

    if operation == "start":
        if is_screen_session_running(screen_session_name):
            logging.error(
                f"Screen session {screen_session_name} may already be running."
            )
            return
        start_cmd = f"screen -dmS {screen_session_name} {python_executable} {shlex.quote(python_program_path)}"
        print(start_cmd)
        subprocess.Popen(start_cmd, shell=True)
        logging.info(
            f"Screen session {screen_session_name} started with program {program_name}"
        )

    elif operation == "stop":
        if not is_screen_session_running(screen_session_name):
            logging.error(f"Screen session {screen_session_name} may not be running.")
            return

        stop_cmd = f"screen -S {screen_session_name} -X quit"
        subprocess.Popen(stop_cmd, shell=True)
        logging.info(f"Screen session {screen_session_name} stopped")

    elif operation == "restart":
        if is_screen_session_running(screen_session_name):
            manage_process_screen(python_program_path, "stop")
            time.sleep(1)  # Wait a bit for the session to be fully stopped
        manage_process_screen(python_program_path, "start")

    else:
        logging.error(f"Unsupported operation: {operation}")


def intel_sort():
    from app import db
    from app.models import ActiveEvents, EventOrder, EventType
    from sqlalchemy import or_
    from app.lib.db_func import map_database_files

    # Debug information
    print("Starting intel_sort function")

    # Get all event types and orders
    event_types = EventType.query.all()
    event_orders = EventOrder.query.order_by(EventOrder.order).all()

    # Print debug information about event orders
    print("Event Orders (sorted by order):")
    for order in event_orders:
        print(f"Order: {order.order}, Name: {order.name}")

    # Create a mapping of event order names to their order values for quick lookup
    order_priority = {order.name: order.order for order in event_orders}

    # Get all active events
    active_events = ActiveEvents.query.all()

    # Group events by event type
    events_by_type = {}
    for event_type in event_types:
        # Filter events that belong to this type
        type_events = [
            event for event in active_events if event_type.name in event.event_name
        ]
        events_by_type[event_type.name] = type_events
        print(f"Found {len(type_events)} events for type: {event_type.name}")

    # Process each event type group
    global_sort_index = 1
    for type_name, events in events_by_type.items():
        if not events:
            continue

        # Find the event type object
        event_type = next((et for et in event_types if et.name == type_name), None)
        if not event_type:
            continue

        # Assign order priority based on event order
        for event in events:
            # Find which event order this event belongs to
            event_order_name = None
            event_order_value = float("inf")  # Default to high value if no match

            for order_name, order_value in order_priority.items():
                if order_name in event.event_name:
                    # If multiple orders match, take the one with lowest order value
                    if order_value < event_order_value:
                        event_order_name = order_name
                        event_order_value = order_value

            # Store the order value as a temporary attribute
            event.temp_order_value = event_order_value
            print(f"Event: {event.event_name}, Order Value: {event_order_value}")

        # Sort events within this type
        if event_type.finish_heat:
            # Sort by run first, then by order priority
            sorted_events = sorted(events, key=lambda x: (x.run, x.temp_order_value))
        else:
            # Sort just by order priority
            sorted_events = sorted(events, key=lambda x: x.temp_order_value)

        # Assign global sort order
        for event in sorted_events:
            event.sort_order = global_sort_index
            global_sort_index += 1
            # Remove temp attribute
            delattr(event, "temp_order_value")

        # Commit changes for this group
        db.session.add_all(sorted_events)
        db.session.commit()
        print(f"Updated sort order for {len(sorted_events)} events of type {type_name}")

    # Final verification
    final_events = ActiveEvents.query.order_by(ActiveEvents.sort_order).all()
    print("Final sort order:")
    for event in final_events:
        print(f"Sort: {event.sort_order}, Event: {event.event_name}")

    return "Sorting completed successfully"


def get_event_data_all(event):
    import json

    g_config = GetEnv()
    with sqlite3.connect(event[0]["db_file"]) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM drivers;".format(event[0]["db_file"]))
        drivers = cursor.fetchall()
        data = {}

        for a in event[0]["SPESIFIC_HEAT"]:
            cursor.execute(
                "SELECT CID, INTER_1, INTER_2, INTER_3, SPEED, PENELTY, FINISHTIME, LOCKED, STATE FROM driver_stats_r{0};".format(
                    a
                )
            )
            driver_stats = cursor.fetchall()

            cursor.execute("SELECT * FROM startlist_r{0};".format(a))
            driver_startlist = cursor.fetchall()

            for start_entry in driver_startlist:
                for row in driver_stats:
                    driver = next((d for d in drivers if d[0] == row[0]), None)
                    if driver:
                        if driver[2] == "FILLER" or driver[1] == "FILLER":
                            newdata = list(driver)
                            newdata[3] = "FILLER"
                            newdata[4] = "FILLER"
                            driver = tuple(newdata)

                        if a not in data:
                            data[a] = []

                        if row[0] == start_entry[1]:
                            if (driver[:5] + row[4:7]) not in data[a]:
                                data[a].append(driver[:5] + row[4:7])
    return data


def get_active_events_sorted():
    from app.models import ActiveEvents
    from app.lib.db_operation import get_active_event

    event_order = ActiveEvents.query.order_by(ActiveEvents.sort_order).all()
    current_active_event = get_active_event()[0]

    data = []

    for a in event_order:
        if str(a.event_file) == str(current_active_event["db_file"]) and str(
            current_active_event["SPESIFIC_HEAT"]
        ) == str(a.run):
            state = True
        else:
            state = False
        data.append(
            {
                "Order": a.sort_order,
                "Event": a.event_name,
                "Enabled": a.enabled,
                "Heat": a.run,
                "Active": state,
                "Mode": a.mode,
            }
        )

    return data


def set_active_event(event, heat, drivers=None, event_id=None):
    from app import db as my_db
    from app.models import Session_Race_Records

    if drivers != None:
        pass

    if event_id != None:

        my_db.session.query(Session_Race_Records).filter(Session_Race_Records.active_event == True).update({'active_event': False})
        my_db.session.query(Session_Race_Records).filter(Session_Race_Records.event_id == event_id).update({'active_event': True})
        my_db.session.commit()
    
    else:

        my_db.session.query(Session_Race_Records).filter(Session_Race_Records.active_event == True).update({'active_event': False})
        my_db.session.query(Session_Race_Records).filter(Session_Race_Records.title_2 == event, Session_Race_Records.heat == heat).update({'active_event': True})
        my_db.session.commit()

def convert_to_remote_data_struct(content, race_type=None):
    data_dict = content["time_info"]
    heat = content["HEAT"]
    heats = content["HEATS"]
    race_title = content["TITLE_2"]
    mode = race_type

    race_config = {
        "race_config": {
            "TITLE_1": content.get("TITLE_1", ""),
            "TITLE_2": race_title,
            "HEAT": heat,
            "HEATS": heats,
            "MODE": mode,
        }
    }

    result = [race_config]

    for a in data_dict:
        penalty = 0 if a["penalty"] == '' else a["penalty"]

        driver = {
            "id": a.get("id"),
            "first_name": a["first_name"],
            "last_name": a["last_name"],
            "club": a["club"],
            "vehicle": a["snowmobile"],
            "active": a.get("active", False),
            "status": a.get("status", "None"),
            "time_info": {
                "FINISHTIME": a["totaltime"],
                "INTER_1": a["laps"],
                "INTER_2": a["best_time"],
                "INTER_3": 0,
                "PENELTY": penalty,
                "SPEED": a["timedata"],
                "POINTS": a.get("points", 0),
            }
        }

        result.append({"drivers": [driver]})

    return result

def get_event_data(event=None, all_events=False, heat=None):
    from app.models import Session_Race_Records, ActiveEvents
    from app import db
    from flask import current_app
    from app.lib.db_operation import get_active_event
    
    
    race_type = int(GetEnv()["race_type"])
    
    def generate_meta(entry_meta):

        d = entry_meta.data or {}
        event_name = d.get("event_name") or d.get("title_1", "")
        run_name = entry_meta.title_2
        heat = int(entry_meta.heat)

        event_meta = ActiveEvents.query.filter(ActiveEvents.event_name == run_name, ActiveEvents.run == heat).first()

        # MSport: derive display type from module field.
        # module "0" = drag (non-parallel); module "2"/"3" = parallel.
        module = d.get("module")
        if module is not None:
            effective_race_type = 3 if module in ("2", "3") else 0
        else:
            effective_race_type = race_type

        total_heats = db.session.query(db.func.count(db.func.distinct(Session_Race_Records.heat))).filter(
            Session_Race_Records.title_2 == run_name
        ).scalar() or 1

        event_meta_dict = {
            "RACE_TYPE": effective_race_type,
            "EVENT_CHECKSUM": event_meta.event_checksum if event_meta else entry_meta.event_id,
            "FINISH_CRITERIA": event_meta.finish_criteria if event_meta else None,
            "FINISH_LAPS": event_meta.finish_laps if event_meta else None,
            "FINISH_TIME": event_meta.finish_time if event_meta else None,
            "HEATS": total_heats,
            "HEAT": heat,
            "TITLE_1": event_name,
            "TITLE_2": run_name,
            "MULTI_CLASS": d.get("multi_class", False),
            "FINISHED": d.get("finished", False),
            "ACTIVE_EVENT": bool(entry_meta.active_event),
            "time_info": [],
        }
        return event_meta_dict
    
    data = []
    if all_events:
        entry_meta = Session_Race_Records.query.group_by(Session_Race_Records.heat, Session_Race_Records.title_2).all()

        for a in entry_meta:
            meta_entry = generate_meta(a)
            driver_data = Session_Race_Records.query.filter(Session_Race_Records.title_2 == a.title_2, Session_Race_Records.heat == a.heat).all()
            for b in driver_data:
                meta_entry["time_info"].append(b.data)
            data.append(meta_entry)
        return data
    elif event != None:
        if heat != None:
            entry_meta = Session_Race_Records.query.filter(Session_Race_Records.heat==heat, Session_Race_Records.title_2==event).first()
            if entry_meta == None: 
                return {"ERROR":"NO DATA"}
            data = generate_meta(entry_meta)
            
            driver_entries = Session_Race_Records.query.filter(Session_Race_Records.title_2 == event, Session_Race_Records.heat == heat).all()

            if len(driver_entries) == 0:
                return {"ERROR":"NO DATA"}

            _OLD_FIELDS = {"cid", "first_name", "last_name", "title_1", "title_2",
                           "heat", "finishtime", "snowmobile", "penalty",
                           "reaction", "points", "laps"}
            driver_entries.sort(key=lambda r: (r.data.get("start_pos") or 0))
            for a in driver_entries:
                d = a.data
                entry = {k: d.get(k) for k in _OLD_FIELDS}
                entry["internal_position"] = d.get("position")
                data["time_info"].append(entry)
            
            return data
        else:
            
            entry_meta = Session_Race_Records.query.filter(Session_Race_Records.title_2 == event).group_by(Session_Race_Records.heat).all()
            if len(entry_meta) == 0:
                return {"ERROR":"NO DATA"}
            
            for a in entry_meta:
                meta_entry = generate_meta(a)
                driver_data = Session_Race_Records.query.filter(Session_Race_Records.title_2 == a.title_2, Session_Race_Records.heat == a.heat).all()
                for b in driver_data:
                    meta_entry["time_info"].append(b.data)
                data.append(meta_entry)
            return data
    else:
        event_id = get_active_event()[0]["event_id"]
        print(event_id)
        entry_meta = Session_Race_Records.query.filter(Session_Race_Records.event_id == event_id).first()
        print(entry_meta)
        data = generate_meta(entry_meta)

        driver_entries = Session_Race_Records.query.filter(Session_Race_Records.event_id == event_id).all()
        for a in driver_entries:
            data["time_info"].append(a.data) 

    return data

def create_event_id_checksum(event_entry):
    import zlib
    #The checksum will be based on str(run_name + heat)
    checksum = zlib.crc32(event_entry.encode())
    return f"{checksum:08x}"

def get_cross_results(event=None, heat=None, all_events=False):
    """
    Returns driver results for race_type 5 (Cross), sorted by best_time ascending.
    Drivers with no time (best_time == 0 or missing) go to the bottom.

    Usage:
      - get_cross_results(event="600 Stock - Kvalifisering", heat=2)
          Returns drivers for that specific event+heat, sorted by best lap time.
      - get_cross_results(event="600 Stock - Kvalifisering")
          Returns aggregated results across all heats for that event.
          Each driver appears once with their best best_time across all heats.
      - get_cross_results(all_events=True)
          Returns aggregated results across ALL events and heats.
          Each driver appears once with their overall best best_time.
      - get_cross_results()
          Returns drivers for the currently active event+heat.
    """
    from app.models import Session_Race_Records
    from app import db

    def _aggregate(entries):
        best_by_cid = {}
        for e in entries:
            d = e.data
            cid = str(d.get("cid", ""))
            bt = float(d.get("best_time", 0) or 0)

            if cid not in best_by_cid:
                best_by_cid[cid] = dict(d)
                best_by_cid[cid]["best_time"] = bt
            else:
                existing_bt = float(best_by_cid[cid]["best_time"] or 0)
                if bt > 0 and (existing_bt == 0 or bt < existing_bt):
                    best_by_cid[cid]["best_time"] = bt
        return list(best_by_cid.values())

    if all_events:
        # Aggregated across ALL events and heats
        entries = Session_Race_Records.query.all()
        drivers = _aggregate(entries)
    elif event is not None and heat is not None:
        # Specific event + heat
        entries = Session_Race_Records.query.filter(
            Session_Race_Records.title_2 == event,
            Session_Race_Records.heat == heat
        ).all()
        drivers = [e.data for e in entries]
    elif event is not None:
        # Aggregated across all heats for this event
        entries = Session_Race_Records.query.filter(
            Session_Race_Records.title_2 == event
        ).all()
        drivers = _aggregate(entries)
    else:
        # Active event
        entries = Session_Race_Records.query.filter(
            Session_Race_Records.active_event == True
        ).all()
        drivers = [e.data for e in entries]

    # Sort by best_time ascending; 0/missing go to bottom
    def sort_key(d):
        bt = float(d.get("best_time", 0) or 0)
        if bt <= 0:
            return (1, 0)
        return (0, bt)

    drivers.sort(key=sort_key)

    results = []
    for i, d in enumerate(drivers):
        results.append({
            "position": i + 1,
            "cid": d.get("cid", ""),
            "first_name": d.get("first_name", ""),
            "last_name": d.get("last_name", ""),
            "club": d.get("club", ""),
            "snowmobile": d.get("snowmobile", ""),
            "best_time": float(d.get("best_time", 0) or 0),
            "last_lap_time": d.get("last_lap_time", ""),
            "totaltime": d.get("totaltime", ""),
            "laps": d.get("laps", 0),
            "finished": d.get("finished", False),
        })

    return results


def format_startlist(event, include_timedata=False):
    import json

    g_config = GetEnv()

    if Check_Event(event) == True:
        with sqlite3.connect(event[0]["db_file"]) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM startlist_r{0};".format(event[0]["SPESIFIC_HEAT"])
            )
            startlist_data = cursor.fetchall()
            event_data = cursor.execute(
                "SELECT MODE, RUNS, TITLE1, TITLE2, DATE FROM db_index;"
            ).fetchall()
            event_data_dict = {
                "MODE": event_data[0][0],
                "HEATS": event_data[0][1],
                "HEAT": int(event[0]["SPESIFIC_HEAT"]),
                "TITLE_1": event_data[0][2],
                "TITLE_2": event_data[0][3],
                "DATE": event_data[0][4],
                "CROSS": g_config["cross"],
            }

            cursor.execute("SELECT * FROM drivers")
            drivers_data = cursor.fetchall()

            cursor.execute(
                "SELECT CID, INTER_1, INTER_2, SPEED, PENELTY, FINISHTIME, REACTION FROM driver_stats_r{0};".format(
                    event[0]["SPESIFIC_HEAT"]
                )
            )
            time_data = cursor.fetchall()

            drivers_dict = {driver[0]: driver[1:] for driver in drivers_data}
            structured_races = []
            structured_races.append({"race_config": event_data_dict})

            if event_data_dict["MODE"] == 3 or event_data_dict["MODE"] == 2:
                active_drivers = Get_active_drivers(g_config, event_data_dict)
                driver_entries = []
                count = 0
                for b in range(0, int(len(startlist_data) / 2)):
                    driver_entries.append(
                        (b + 1, startlist_data[count][1], startlist_data[count + 1][1])
                    )
                    count = count + 2
            else:
                active_drivers = Get_active_drivers(g_config, event_data_dict)
                driver_entries = []
                count = 0

                for b in range(0, int(len(startlist_data))):
                    driver_entries.append((b + 1, startlist_data[count][1]))
                    count = count + 1

            for race in driver_entries:
                race_id = race[0]
                drivers_in_race = []
                for driver_id in race[1:]:
                    driver_data = drivers_dict.get(driver_id)
                    if driver_data:
                        if int(driver_id) in active_drivers.values():
                            active = True
                        else:
                            active = False

                        driver_info = {
                            "id": driver_id,
                            "first_name": driver_data[0],
                            "last_name": driver_data[1],
                            "club": driver_data[2],
                            "vehicle": driver_data[3],
                            "active": active,
                        }
                        for a in time_data:
                            if str(a[0]) == str(driver_id):
                                driver_info["time_info"] = {
                                    "INTER_1": a[1],
                                    "INTER_2": a[2],
                                    "SPEED": a[3],
                                    "PENELTY": a[4],
                                    "FINISHTIME": a[5],
                                    "REACTION": a[6],
                                }
                                if a[5] == 0 or a[4] != 0:
                                    driver_info["status"] = 0
                                    started = False

                        drivers_in_race.append(driver_info)

                        if event_data_dict["MODE"] == 3 or event_data_dict["MODE"] == 2:
                            if len(drivers_in_race) == 2:
                                if drivers_in_race[0]["time_info"]["PENELTY"] > 0:
                                    drivers_in_race[1]["status"] = 1
                                    drivers_in_race[0]["status"] = 2

                                elif drivers_in_race[1]["time_info"]["PENELTY"] > 0:
                                    drivers_in_race[0]["status"] = 1
                                    drivers_in_race[1]["status"] = 2

                                if (
                                    "status" in drivers_in_race[0]
                                    and drivers_in_race[1]["time_info"]["FINISHTIME"]
                                    and drivers_in_race[1]["time_info"]["PENELTY"] == 0
                                ):
                                    # print(drivers_in_race[0]["first_name"], "WINNER 1")
                                    drivers_in_race[1]["status"] = 1
                                    drivers_in_race[0]["status"] = 2

                                elif (
                                    "status" in drivers_in_race[1]
                                    and drivers_in_race[0]["time_info"]["FINISHTIME"]
                                    and drivers_in_race[1]["time_info"]["PENELTY"] == 0
                                ):
                                    # print(drivers_in_race[1]["first_name"], "WINNER 0")
                                    drivers_in_race[0]["status"] = 1
                                    drivers_in_race[1]["status"] = 2

                                if (
                                    drivers_in_race[0]["time_info"]["FINISHTIME"]
                                    < drivers_in_race[1]["time_info"]["FINISHTIME"]
                                    and not "status" in drivers_in_race[0]
                                ):
                                    # print(drivers_in_race[0]["first_name"], "WINNER 1")
                                    drivers_in_race[0]["status"] = 1
                                    drivers_in_race[1]["status"] = 2

                                elif (
                                    drivers_in_race[0]["time_info"]["FINISHTIME"]
                                    > drivers_in_race[1]["time_info"]["FINISHTIME"]
                                    and not "status" in drivers_in_race[1]
                                ):
                                    # print(drivers_in_race[1]["first_name"], "WINNER 0")
                                    drivers_in_race[1]["status"] = 1
                                    drivers_in_race[0]["status"] = 2

                        elif event_data_dict["MODE"] == 0:
                            race_id = int(event[0]["SPESIFIC_HEAT"])

                race_info = {
                    "race_id": race_id,
                    "drivers": drivers_in_race,
                }

                structured_races.append(race_info)
        return structured_races
    else:
        logging.error(f"Active event not initiated operation")
        return "None"


def get_active_event_name():
    pass


def reorder_list_based_on_dict(original_list, correct_order_dict):
    new_list = []
    temp_dict = {}

    for name, score in original_list:
        if score in temp_dict:
            temp_dict[score].append(name)
        else:
            temp_dict[score] = [name]

    for item in original_list:
        name, score = item
        # Check if this score needs reordering and if the name is in the correct order list
        if score in correct_order_dict and name in correct_order_dict[score]:
            # If the name is the next one to be placed according to the dictionary, add it to the new list
            if name == correct_order_dict[score][0]:
                new_list.append(item)
                correct_order_dict[score].pop(
                    0
                )  # Remove the added name from the dictionary list
        else:
            # For scores not needing reordering or already handled, add them directly
            if name in temp_dict[score]:
                new_list.append(item)
                temp_dict[score].remove(
                    name
                )  # Remove the added name from the temp_dict list

    return new_list


def get_active_driver_name(event_id, cid):
    from app.models import Session_Race_Records
    
    #query = "SELECT FIRST_NAME, LAST_NAME FROM drivers WHERE CID={0};".format(cid)
    print(event_id, cid)
    data = Session_Race_Records.query.filter(Session_Race_Records.cid==cid).first().data
    first_name = data["first_name"]
    last_name = data["last_name"]
    return first_name + " " + last_name


def fifo_monitor(app, fifo_path="/tmp/file_monitor_fifo", callback=None, g_config=None):
    import json

    if g_config.use_intermediate == True:
        g_config.event_dir = g_config.intermediate_path

    if not os.path.exists(fifo_path):
        os.mkfifo(fifo_path)

    def monitor_fifo():
        from app.lib.db_operation import full_db_reload
        import sqlite3
        import json
        import re
        import time

        fifo = os.open(fifo_path, os.O_RDONLY | os.O_NONBLOCK)
        poll = select.poll()
        poll.register(fifo, select.POLLIN)

        DB_PATH = "/mnt/intermediate/Online.scdb"
        with sqlite3.connect(DB_PATH) as con:
            cur = con.cursor()
            active_event = cur.execute("SELECT C_PARAM WHERE WHERE ;").fetchone()[0]

        while True:
            if poll.poll(1000):
                try:
                    data = os.read(fifo, 4096).decode().strip()

                    if str(data) == "Online.scdb":
                        print("Online DB")
                        with sqlite3.connect(DB_PATH) as con:
                            cur = con.cursor()
                            time.sleep(2)
                            active_event = cur.execute(
                                "SELECT EVENT FROM active_drivers;"
                            ).fetchone()[0]
                    else:
                        event_change = re.findall(r"\d+", data)
                        try:
                            if len(event_change) == 0:
                                print("FAIL", data)

                            else:
                                # full_db_reload(add_intel_sort=False, Event=file)
                                print("NOT ACTIVE", event_change)
                        except:
                            print("Error")

                    if data and callback:
                        with app.app_context():
                            callback(data)
                except OSError:
                    pass

    thread = Thread(target=monitor_fifo, daemon=True)
    thread.start()

    return app


def update_led_panel_state():
    from flask import current_app
    from app import mqtt_client

    g_config = GetEnv()
    DB_PATH = "site.db"
    g_config = GetEnv()
    title_2 = json.loads(current_app.config["event_content"])[0]["race_config"][
        "TITLE_2"
    ]
    if current_app.config["stage_ready"] == 1:
        value = json.dumps({"picker": None, "ready": True})
    elif "stige" not in title_2.lower():
        value = json.dumps({"picker": None, "ready": True})

    else:
        with sqlite3.connect(g_config["project_dir"] + "site.db") as conn:
            cursor = conn.cursor()
            active_drivers_sql = cursor.execute(
                "SELECT D1, D2 FROM active_drivers"
            ).fetchall()

            active_drivers = {
                "D1": active_drivers_sql[0][0],
                "D2": active_drivers_sql[0][1],
            }

            kvali_title = title_2.replace("Stige", "Kvalifisering")
            active_driver_best_time = get_best_kvali_time(active_drivers, kvali_title)
            # value = json.dumps({"picker":str(active_driver_best_time[0]), "ready":True})
            value = json.dumps({"picker": None, "ready": True})

    mqtt_client.connect("localhost", 1883, 60)
    mqtt_client.publish("staging_state_led", value)
