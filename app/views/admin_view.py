from flask import Blueprint, render_template, request, url_for, redirect, flash
from app.lib.db_operation import *
from app.lib.utils import GetEnv, intel_sort, update_info_screen, export_events
import json
from werkzeug.utils import secure_filename
import requests


admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/admin/", methods=["GET"])
def admin_home():
    return home_tab()


@admin_bp.route("/admin/<string:tab_name>", methods=["GET", "POST"])
def admin(tab_name):
    if tab_name == "home":
        return home_tab()
    elif tab_name == "global-config":
        return global_config_tab()
    elif tab_name == "start_logic":
        return start_logic()
    elif tab_name == "s_set_active_driver":
        return s_set_active_driver()
    elif tab_name == "standing_config":
        return standing_config_tab()
    elif tab_name == "race_setup":
        return race_setup_tab()
    elif tab_name == "infoscreen":
        return infoscreen()
    elif tab_name == "active_events":
        return active_events()
    elif tab_name == "active_events_driver_data":
        return active_events_driver_data()
    elif tab_name == "msport_proxy":
        return msport_proxy()
    elif tab_name == "export":
        return export_data()
    elif tab_name == "clock_mgnt":
        return clock_mgnt()
    elif tab_name == "time_keeper":
        return timekeeperpage()
    elif tab_name == "ledpanel":
        return led_panel()
    elif tab_name == "kvali_criteria":
        return kvali_criteria()
    elif tab_name == "stream_overlay":
        return stream_overlay()
    elif tab_name == "race_results":
        return race_results()
    else:
        return "Invalid tab", 404


def s_set_active_driver():
    from flask import current_app

    list_address = current_app.config["listen_address"]

    DB_PATH = "site.db"
    if request.method == "POST":
        active_driver_id = request.json["driverId"]
        with sqlite3.connect(DB_PATH) as con:
            cur = con.cursor()
            cur.execute("UPDATE active_drivers SET  D1 = ?;", (active_driver_id,))

        requests.get("http://{0}:7777/api/update_event?active=True".format(list_address))

        con.commit()
        return {"synced": "True"}

    return render_template("admin/s_set_active_driver.html")


def publish(client, msg, topic_dev):
    result = client.publish(topic_dev, msg, retain=True)
    status = result[0]
    if status == 0:
        print(f"Send `{msg}` to topic `{topic_dev}`")
    else:
        print(f"Failed to send message to topic {topic_dev}")


def start_logic():
    from app.lib.utils import GetEnv
    from app.models import StartLogic, MicroServices
    from flask import request, redirect, url_for, render_template
    import json, base64
    from PIL import Image
    from app import db
    import io
    from requests.exceptions import HTTPError
    from app.lib.utils import manage_process_screen
    import time
    from flask import current_app

    g_conf = GetEnv()
    start_data = StartLogic.query.first()

    if request.method == "POST":
        mqtt_mw_state = MicroServices.query.filter(
            MicroServices.path == "mqtt_middleware.py"
        ).first()

        if "start_light_ip" not in request.form:
            import paho.mqtt.publish as publish

            current_state = current_app.config["start_state"]
            for a in current_state:
                if a in request.form:
                    current_state[a] = True
                else:
                    current_state[a] = False
            publish.single(
                "start/state", payload=json.dumps(current_state), hostname="127.0.0.1"
            )
            return redirect(url_for("admin.admin", tab_name="start_logic"))

        def hex_to_rgb_string(hex_color):
            hex_color = hex_color.lstrip("#")
            rgb = tuple(int(hex_color[i: i + 2], 16) for i in (0, 2, 4))
            return str(list(rgb))

        start_data.start_light_ip = request.form["start_light_ip"]
        start_data.sl_matric_size = request.form["sl_matric_size"]
        start_data.sl_start_delay = request.form["sl_start_delay"]
        start_data.sl_active_timer = int(request.form["sl_active_timer"])
        start_data.sl_halt_color = hex_to_rgb_string(request.form["sl_halt_color"])
        start_data.sl_start_color = hex_to_rgb_string(request.form["sl_start_color"])
        start_data.sl_stop_color = hex_to_rgb_string(request.form["sl_stop_color"])
        start_data.sl_ready_color = hex_to_rgb_string(request.form["sl_ready_color"])
        start_data.sl_brightness = request.form["sl_brightness"]

        # Warmup durations
        if request.form.get("sl_warmup_duration_1"):
            start_data.sl_warmup_duration_1 = float(request.form["sl_warmup_duration_1"])
        if request.form.get("sl_warmup_duration_2"):
            start_data.sl_warmup_duration_2 = float(request.form["sl_warmup_duration_2"])

        if "use_orbits" in request.form:
            start_data.use_orbits = True
        else:
            start_data.use_orbits = False

        if "req_orbits_warmup" in request.form:
            start_data.req_orbits_warmup = True
        else:
            start_data.req_orbits_warmup = False

        if "sl_start_using_relay" in request.form:
            start_data.sl_start_using_relay = True
        else:
            start_data.sl_start_using_relay = False

        # Warmup image 1
        image_data_raw = request.form.get("sl_warmup_image_data")
        if image_data_raw:
            print(f"Received warmup image 1 data, length: {len(image_data_raw)}")
            image_data = image_data_raw.split(",")[1]
            image_bytes = base64.b64decode(image_data)
            img = Image.open(io.BytesIO(image_bytes))
            img_io = io.BytesIO()
            img.save(img_io, "PNG")
            start_data.sl_warmup_image = img_io.getvalue()
            print(f"Saved warmup image 1, size: {len(start_data.sl_warmup_image)} bytes")
        else:
            print("No warmup image 1 data received")

        # Warmup image 2 (optional)
        image_data_2_raw = request.form.get("sl_warmup_image_data_2")
        if image_data_2_raw:
            print(f"Received warmup image 2 data, length: {len(image_data_2_raw)}")
            image_data_2 = image_data_2_raw.split(",")[1]
            image_bytes_2 = base64.b64decode(image_data_2)
            img2 = Image.open(io.BytesIO(image_bytes_2))
            img_io_2 = io.BytesIO()
            img2.save(img_io_2, "PNG")
            start_data.sl_warmup_image_2 = img_io_2.getvalue()
            print(f"Saved warmup image 2, size: {len(start_data.sl_warmup_image_2)} bytes")
        else:
            print("No warmup image 2 data received")

        start_data.fc_req_ready = "fc_req_ready" in request.form
        start_data.cr_req_ready = "cr_req_ready" in request.form
        start_data.fc_can_start = "fc_can_start" in request.form
        start_data.cr_can_start = "cr_can_start" in request.form
        start_data.sl_use_warmup_image = "sl_use_warmup_image" in request.form
        start_data.sl_use_warmup_image_2 = "sl_use_warmup_image_2" in request.form

        if "sl_start_using_relay" in request.form:
            use_relay = str(True)
        else:
            use_relay = str(False)

        db.session.commit()

        try:
            data = request.form.to_dict(flat=False)
            data["sl_start_using_relay"] = use_relay
            data["sl_halt_color"] = start_data.sl_halt_color
            data["sl_start_color"] = start_data.sl_start_color
            data["sl_stop_color"] = start_data.sl_stop_color
            data["sl_ready_color"] = start_data.sl_ready_color
            data["sl_warmup_duration_1"] = str(start_data.sl_warmup_duration_1)
            data["sl_warmup_duration_2"] = str(start_data.sl_warmup_duration_2)
            data["sl_use_warmup_image_2"] = str(start_data.sl_use_warmup_image_2)

            fresh = StartLogic.query.first()
            rgb_values = fresh.get_rgb_values()
            data["sl_warmup_image_data"] = rgb_values["image_1"]
            data["sl_warmup_image_data_2"] = rgb_values["image_2"]

            requests.post(
                f"http://{start_data.start_light_ip}/api/set_config",
                json=json.dumps(data),
            )

        except Exception as err:
            print(err)

        if mqtt_mw_state.state:
            manage_process_screen("mqtt_middleware.py", "stop")
            time.sleep(1)
            manage_process_screen("mqtt_middleware.py", "start")

        return redirect(url_for("admin.admin", tab_name="start_logic"))

    def rgb_to_hex(rgb_string):
        try:
            rgb = json.loads(rgb_string)
            return "#{:02x}{:02x}{:02x}".format(rgb[0], rgb[1], rgb[2])
        except:
            return "#000000"

    matrix_size = start_data.sl_matric_size or "24x32"
    matrix_width, matrix_height = map(int, matrix_size.split("x"))

    try:
        requests.get("http://" + start_data.start_light_ip, timeout=1)
        endpoint_state = True
    except:
        endpoint_state = False

    start_state_field = current_app.config["start_state"]

    # Prepare image data as JSON-safe values
    warmup_img_1 = None
    if start_data.sl_warmup_image:
        warmup_img_1 = base64.b64encode(start_data.sl_warmup_image).decode()

    warmup_img_2 = None
    if start_data.sl_warmup_image_2:
        warmup_img_2 = base64.b64encode(start_data.sl_warmup_image_2).decode()

    return render_template(
        "admin/start_logic.html",
        config=start_data,
        start_state_field=start_state_field,
        endpoint_state=endpoint_state,
        matrix_width=matrix_width,
        matrix_height=matrix_height,
        halt_color_hex=rgb_to_hex(start_data.sl_halt_color)
            if start_data.sl_halt_color else "#ff0000",
        start_color_hex=rgb_to_hex(start_data.sl_start_color)
            if start_data.sl_start_color else "#00ff00",
        stop_color_hex=rgb_to_hex(start_data.sl_stop_color)
            if start_data.sl_stop_color else "#0000ff",
        ready_color_hex=rgb_to_hex(start_data.sl_ready_color)
            if start_data.sl_ready_color else "#000000",
        warmup_image_b64=warmup_img_1,
        warmup_image_2_b64=warmup_img_2,
    )


def home_tab():
    from app.models import (
        ActiveDrivers,
        ActiveEvents,
        Session_Race_Records,
        GlobalConfig,
        MicroServices,
        archive_server,
    )
    from app import db
    from sqlalchemy import func
    import json

    archive_params = archive_server.query.first()

    archive_params_json = {
        "password": archive_params.auth_token,
        "hostname": archive_params.hostname,
        "enabled": archive_params.enabled,
    }

    g_conf = db.session.query(
        GlobalConfig.db_location,
        GlobalConfig.event_dir,
        GlobalConfig.use_intermediate,
        GlobalConfig.intermediate_path,
    ).all()[0]

    db_location = g_conf[0]
    mount_path = g_conf[1]
    use_inter = g_conf[2]
    intermediate_path = g_conf[3]

    mount_bool = os.path.ismount(mount_path)

    if mount_bool == False:
        mount_bool = str(2)
    else:
        if use_inter == True:
            inter_files = g_conf[3]
            dir = os.listdir(inter_files)

            if len(dir) == 0:
                mount_bool = str(3)
            else:
                mount_bool = str(1)
        else:
            mount_bool = str(1)

    # Query to get distinct event names and their counts
    enabled_events = (
        ActiveEvents.query.filter(ActiveEvents.enabled == 1)
        .group_by(ActiveEvents.event_name)
        .with_entities(ActiveEvents.event_name, func.count(ActiveEvents.event_name))
        .count()
    )

    drivers = (
        Session_Race_Records.query
        .with_entities(Session_Race_Records.cid)
        .distinct()
        .count()
    )
    
    services = MicroServices.query.all()

    number_runs = ActiveEvents.query.filter(ActiveEvents.enabled == 1).count()

    unique_events = (
        db.session.query(
            ActiveEvents.event_name,
            func.max(ActiveEvents.run).label("max_run"),
            ActiveEvents.event_file,
        )
        .group_by(ActiveEvents.event_name)
        .order_by(ActiveEvents.sort_order)
        .all()
    )
    print(len(unique_events))

    if request.method == "POST":
        if "endpoint_server_update" in request.form:
            hostname = request.form.get("hostname")
            password = request.form.get("password")
            state = request.form.get("state")

            if password == "":
                token = False
            else:
                token = True

            archive_params = archive_server.query.first()

            if state == "none":
                archive_params.hostname = hostname
                archive_params.auth_token = password
                archive_params.use_use_token = token
                db.session.commit()
            else:
                if state == "start":
                    state = True
                else:
                    state = False
                archive_params.hostname = hostname
                archive_params.auth_token = password
                archive_params.use_use_token = token
                archive_params.enabled = state

                db.session.commit()

            return {"Success": "Updated configuration"}

        elif "single_event" in request.form:
            if request.form.get("event_file") == "active_event":
                active_event = get_active_event()
                selectedEventFile = active_event[0]["db_file"]
            else:
                selectedEventFile = request.form.get("single_event")
                sync_state = request.form.get("sync")

                if sync_state == "true":
                    from app.lib.utils import GetEnv
                    event_name = request.form.get("event_name")

                    db.session.query(Session_Race_Records).filter(
                        Session_Race_Records.title_2 == event_name
                    ).delete()
                    db.session.commit()
                    full_db_reload(add_intel_sort=False, Event=selectedEventFile)

            print("Getting:", selectedEventFile)

            heat_num = (
                db.session.query(func.max(Session_Race_Records.heat))
                .filter(Session_Race_Records.title_2 == selectedEventFile)
                .scalar()
            ) or 0

            amount_drivers = (
                db.session.query(Session_Race_Records.cid)
                .filter(Session_Race_Records.title_2 == selectedEventFile)
                .distinct()
                .count()
            )

            valid_recorded_times = 0
            invalid_recorded_times = 0
            drivers_left = 0

            records = Session_Race_Records.query.filter_by(
                title_2=selectedEventFile
            ).all()

            for r in records:
                data = r.data or {}
                position = str(data.get("position", ""))
                finished = data.get("finished", False)

                if not position.isdigit():
                    # DSQ, DNF, DNS etc.
                    invalid_recorded_times += 1
                elif finished:
                    valid_recorded_times += 1
                else:
                    drivers_left += 1

            event_config = {
                "all_records": valid_recorded_times + invalid_recorded_times + drivers_left,
                "p_times": invalid_recorded_times,
                "v_times": valid_recorded_times,
                "l_times": drivers_left,
                "drivers": amount_drivers,
                "heats": heat_num,
            }
            return event_config

        elif "service_state" in request.form:
            from app.lib.utils import (
                GetEnv,
                is_screen_session_running,
                manage_process_screen,
            )

            from time import sleep

            service_name = request.form.get("service_name")
            service_state = request.form.get("service_state")
            params = request.form.get("ip_address")

            if service_name == None:
                return "None"

            service_object = (
                db.session.query(MicroServices)
                .filter((MicroServices.name == service_name))
                .first()
            )

            if service_object is not None:
                if bool(service_object.state) == False and service_state == "start":
                    service_object.state = True

                    if params != None:
                        service_object.params = params
                    db.session.commit()
                    manage_process_screen(service_object.path, "start")
                    sleep(1)

                    if is_screen_session_running(service_object.path) == True:
                        return "True"
                    else:
                        return "False"

                elif bool(service_object.state) == True and service_state == "stop":
                    service_object.state = False
                    db.session.commit()

                    manage_process_screen(service_object.path, "stop")
                    sleep(1)
                    if is_screen_session_running(service_object.path) == False:
                        return "True"
                    else:
                        return "False"

                elif bool(service_object.state) == True and service_state == "restart":
                    print("Restart")

    return render_template(
        "admin/index.html",
        drivercount=drivers,
        num_run=number_runs,
        num_events=enabled_events,
        events=unique_events,
        microservices=services,
        mount_bool=mount_bool,
        mount_path=mount_path,
        archive_params_json=archive_params_json,
    )


def kvali_criteria():
    from app.models import EventKvaliRate
    from app import db

    if request.method == "POST":
        data = request.get_json()
        EventKvaliRate.query.delete()
        data_len = len(data)

        for k, a in enumerate(dict(data).keys()):
            kvali_num = data[a]
            new_entry = EventKvaliRate(id=k + 1, event=a, kvalinr=int(kvali_num))
            db.session.add(new_entry)
        db.session.commit()
        return {"Success": "True"}

    else:
        kvali_criteria = [event.to_dict() for event in EventKvaliRate.query.all()]
        return render_template(
            "admin/kval_criteria.html", kvali_criteria=kvali_criteria
        )


def standing_config_tab():
    from app.models import StandingConfig, db

    standing_config = StandingConfig.query.first()

    if request.method == "POST":
        scoring_method = request.form.get("scoring_method", "best_lap")

        if not standing_config:
            standing_config = StandingConfig()
            db.session.add(standing_config)

        standing_config.scoring_method = scoring_method
        standing_config.mix_classes = request.form.get("mix_classes") == "on"
        standing_config.use_tiebreaker = request.form.get("use_tiebreaker") == "on"
        standing_config.tiebreaker_method = request.form.get("tiebreaker_method", "")
        standing_config.use_points = request.form.get("use_points") == "on"

        if standing_config.use_points:
            standing_config.dnf_point = request.form.get("dnf_point", 0, type=int)
            standing_config.dns_point = request.form.get("dns_point", 0, type=int)
            standing_config.dsq_point = request.form.get("dsq_point", 0, type=int)
            standing_config.invert_score = request.form.get("invert_score") == "true"

            num_drivers = request.form.get("num_drivers", 0, type=int)
            driver_scores = {}
            for i in range(1, num_drivers + 1):
                score = request.form.get(f"driver_scores[{i}]", type=int)
                if score is not None:
                    driver_scores[i] = score
            standing_config.driver_scores = driver_scores

        db.session.commit()
        return redirect(url_for("admin.admin", tab_name="standing_config"))

    scoring_method = (standing_config.scoring_method or "best_lap") if standing_config else "best_lap"
    driver_scores_json = json.dumps(standing_config.driver_scores) if standing_config and standing_config.driver_scores else "{}"
    return render_template(
        "admin/standing_config_tab.html",
        config=standing_config,
        scoring_method=scoring_method,
        driver_scores_json=driver_scores_json,
    )


def _get_or_create_standing_config(stage):
    from app.models import StandingConfig
    from app import db
    sc = StandingConfig.query.filter_by(stage=stage).first()
    if not sc:
        sc = StandingConfig(stage=stage)
        db.session.add(sc)
        db.session.commit()
    return sc


def _standing_config_to_dict(sc):
    if not sc:
        return {}
    return {
        "scoring_method": sc.scoring_method or "best_lap",
        "mix_classes": sc.mix_classes,
        "use_tiebreaker": sc.use_tiebreaker,
        "tiebreaker_method": sc.tiebreaker_method or "",
        "use_points": sc.use_points,
        "dnf_point": sc.dnf_point,
        "dns_point": sc.dns_point,
        "dsq_point": sc.dsq_point,
        "invert_score": sc.invert_score,
        "driver_scores": sc.driver_scores or {},
    }


def _save_standing_config(sc, data):
    from app import db
    sc.scoring_method = data.get("scoring_method", "best_lap")
    sc.mix_classes = data.get("mix_classes", False)
    sc.use_tiebreaker = data.get("use_tiebreaker", False)
    sc.tiebreaker_method = data.get("tiebreaker_method", "")
    sc.use_points = data.get("use_points", False)
    if sc.use_points:
        sc.dnf_point = data.get("dnf_point", 0)
        sc.dns_point = data.get("dns_point", 0)
        sc.dsq_point = data.get("dsq_point", 0)
        sc.invert_score = data.get("invert_score", False)
        sc.driver_scores = data.get("driver_scores", {})
    db.session.commit()


def race_setup_tab():
    from app.models import GlobalConfig, ActiveEvents, EventKvaliRate, StandingConfig
    from app import db

    config = GlobalConfig.query.first()

    if request.method == "POST":
        if request.content_type and "application/json" in request.content_type:
            data = request.get_json()

            # Save standing config for a stage (1=qualifying, 2=finale)
            if data and "standing_config" in data:
                stage = data.get("stage", 1)
                sc = _get_or_create_standing_config(stage)
                _save_standing_config(sc, data["standing_config"])
                return {"success": True}

            # Save default finish criteria and apply to non-overridden events
            if data and "race_setup" in data:
                if not config:
                    config = GlobalConfig()
                    db.session.add(config)
                config.race_setup = data.get("race_setup", {})
                db.session.commit()

                setup = config.race_setup
                non_overridden = ActiveEvents.query.filter(
                    (ActiveEvents.override_finish == False) | (ActiveEvents.override_finish == None)
                ).all()
                for ev in non_overridden:
                    ev.finish_criteria = setup.get("finish_criteria", "")
                    ev.finish_laps = setup.get("laps", 0)
                    ev.finish_time = setup.get("time_minutes", 0)
                db.session.commit()
                return {"success": True}

            # Save per-event finish overrides
            if data and "event_finish" in data:
                for item in data["event_finish"]:
                    ev = ActiveEvents.query.get(item["id"])
                    if ev:
                        ev.override_finish = bool(item.get("override", False))
                        ev.finish_criteria = item.get("finish_criteria", "")
                        ev.finish_laps = item.get("laps", 0) or 0
                        ev.finish_time = item.get("time_minutes", 0) or 0
                db.session.commit()
                return {"success": True}

            # Save kvali criteria
            if data and "kvali_criteria" in data:
                kvali_data = data["kvali_criteria"]
                EventKvaliRate.query.delete()
                for k, a in enumerate(kvali_data.keys()):
                    new_entry = EventKvaliRate(id=k + 1, event=a, kvalinr=int(kvali_data[a]))
                    db.session.add(new_entry)
                db.session.commit()
                return {"Success": "True"}

        # Handle active events table update (form POST)
        table_data = request.form.get("table_data")
        request_src = request.form.get("src")
        if table_data:
            table_data = json.loads(table_data)
            for k, row in enumerate(table_data):
                k += 1
                if request_src == "orbits":
                    event_name = row["name"]
                    event = ActiveEvents.query.filter(
                        ActiveEvents.event_name == event_name,
                        ActiveEvents.run == row["run"],
                    ).first()
                    row["id"] = event.id
                    row["name"] = event_name

                event = ActiveEvents.query.get(row["id"])
                if event:
                    event.event_name = row["name"]
                    event.run = row["run"]
                    if "enable" in row:
                        event.enabled = row["enable"]
                    if "event_stage" in row:
                        event.event_stage = row["event_stage"]
                    event.sort_order = k
            db.session.commit()

        return redirect(url_for("admin.admin", tab_name="race_setup"))

    race_setup = config.race_setup if config and config.race_setup else {}
    race_type = config.race_type if config else "1"
    msport_tm = config.msport_tm if config else True
    active_events = ActiveEvents.query.order_by(ActiveEvents.sort_order).all()
    kvali_criteria = [event.to_dict() for event in EventKvaliRate.query.all()]

    sc_qualifying = _get_or_create_standing_config(1)
    sc_finale = _get_or_create_standing_config(2)

    return render_template(
        "admin/race_setup_tab.html",
        race_setup=race_setup,
        race_setup_json=json.dumps(race_setup),
        race_type=race_type,
        msport_tm=msport_tm,
        active_events=active_events,
        kvali_criteria=kvali_criteria,
        sc_qualifying=sc_qualifying,
        sc_finale=sc_finale,
        sc_qualifying_json=json.dumps(_standing_config_to_dict(sc_qualifying)),
        sc_finale_json=json.dumps(_standing_config_to_dict(sc_finale)),
    )


def global_config_tab():
    from app.models import (
        GlobalConfig,
        ConfigForm,
        ActiveDrivers,
        Session_Race_Records,
        MicroServices,
        ActiveEvents,
    )
    from app import db
    from app.lib.utils import manage_process_screen, insert_event_data
    from sqlalchemy import asc

    global_config = GlobalConfig.query.all()
    form = ConfigForm()

    if request.method == "POST":
        if "submit" in request.form:
            for config in global_config:
                if not form.wl_cross_title.data:
                    form.wl_cross_title.data = ""

                if form.use_intermediate.data == False:
                    form.intermediate_path.data = form.event_dir.data

                if form.intermediate_path.data[-1:] != "/":
                    form.intermediate_path.data += "/"

                if form.project_dir.data[-1:] != "/":
                    form.project_dir.data += "/"

                if form.db_location.data[-1:] != "/":
                    form.db_location.data += "/"

                if form.event_dir.data[-1:] != "/":
                    form.event_dir.data += "/"

                config.msport_tm = bool(form.msport_tm.data)
                config.session_name = form.session_name.data
                config.project_dir = form.project_dir.data
                config.db_location = form.db_location.data
                config.event_dir = form.event_dir.data
                config.wl_title = form.wl_title.data
                config.wl_bool = bool(form.wl_bool.data)
                config.display_proxy = bool(form.display_proxy.data)
                config.cross = bool(form.cross.data)
                config.keep_previous_sort = form.keep_previous_sort.data
                config.wl_cross_title = form.wl_cross_title.data
                config.exclude_title = form.exclude_title.data
                config.use_intermediate = form.use_intermediate.data
                config.intermediate_path = form.intermediate_path.data
                config.autocommit = form.autocommit.data
                config.keep_qualification = form.keep_qualification.data
                config.race_type = str(form.race_type.data)

                config.normalization_rules = {
                    "qualifying": request.form.get("norm_qualifying", ""),
                    "finale": request.form.get("norm_finale", ""),
                    "other": request.form.get("norm_other", ""),
                }

                if bool(form.cross.data):
                    db.session.query(MicroServices).filter(
                        MicroServices.name == "Cross Clock Server"
                    ).update({"state": True})
                    db.session.commit()
                    manage_process_screen("cross_clock_server.py", "start")
                db.session.commit()
        elif "update" in request.form:
            print("asdasd")
        else:
            keep_previous_sort = global_config[0].keep_previous_sort

            if global_config[0].keep_previous_sort == True:
                ActiveEvents_entries = (
                    ActiveEvents.query.filter(ActiveEvents.id)
                    .order_by(asc(ActiveEvents.sort_order))
                    .all()
                )
                ActiveEvents_list = []
                for h in ActiveEvents_entries:
                    ActiveEvents_list.append(h.id)

            db.session.query(Session_Race_Records).delete()

            if bool(global_config[0].msport_tm) == False:
                insert_event_data(full_sync=True)

            else:
                full_db_reload(add_intel_sort=True)

                if global_config[0].keep_previous_sort == True:
                    order_mapping = {
                        id_value: index for index, id_value in enumerate(ActiveEvents_list)
                    }
                    events = ActiveEvents.query.filter(
                        ActiveEvents.id.in_(ActiveEvents_list)
                    ).all()
                    for event in events:
                        event.sort_order = order_mapping[event.id]

                    db.session.commit()

        return redirect(url_for("admin.admin", tab_name="global-config"))

    return render_template(
        "admin/global_config.html", global_config=global_config, form=form
    )


def active_events():
    from app.models import ActiveEvents, GlobalConfig, EventKvaliRate
    from app import db
    import json

    if request.method == "POST":
        # Handle JSON posts (kvali criteria)
        if request.content_type and "application/json" in request.content_type:
            data = request.get_json()
            if data and "kvali_criteria" in data:
                kvali_data = data["kvali_criteria"]
                EventKvaliRate.query.delete()
                for k, a in enumerate(kvali_data.keys()):
                    new_entry = EventKvaliRate(id=k + 1, event=a, kvalinr=int(kvali_data[a]))
                    db.session.add(new_entry)
                db.session.commit()
                return {"Success": "True"}

        table_data = request.form.get("table_data")
        request_src = request.form.get("src")
        if table_data:
            table_data = json.loads(table_data)
            for k, row in enumerate(table_data):
                k += 1
                if request_src == "orbits":
                    event_name = row["name"]
                    event = ActiveEvents.query.filter(
                        ActiveEvents.event_name == event_name,
                        ActiveEvents.run == row["run"],
                    ).first()
                    row["id"] = event.id
                    row["name"] = event_name

                event = ActiveEvents.query.get(row["id"])
                if event:
                    event.event_name = row["name"]
                    event.run = row["run"]
                    if "enable" in row:
                        event.enabled = row["enable"]
                    event.sort_order = k
            db.session.commit()
            flash("Active events updated successfully.", "success")

        return redirect(url_for("admin.admin", tab_name="active_events"))

    # For GET requests or after POST processing, retrieve and display the active events
    active_events = ActiveEvents.query.order_by(ActiveEvents.sort_order).all()
    kvali_criteria = [event.to_dict() for event in EventKvaliRate.query.all()]
    return render_template(
        "admin/active_events.html",
        active_events=active_events,
        kvali_criteria=kvali_criteria,
    )


def active_events_driver_data():
    from app.models import Session_Race_Records
    from app import db
    from sqlalchemy import func
    from flask import jsonify
    import json

    unique_events = (
        db.session.query(
            Session_Race_Records.title_2,
            func.max(Session_Race_Records.heat).label("max_heat"),
        )
        .group_by(Session_Race_Records.title_2)
        .all()
    )

    extra_keys = ["id", "event_id", "title_2", "active_event", "heat"]

    if request.method == "POST":
        # JSON update from Tabulator
        if request.content_type and "application/json" in request.content_type:
            incoming = request.get_json()
            title_2 = incoming["title_2"]
            heat = int(incoming["heat"])

            for row in incoming["data"]:
                cid = row.pop("CID")
                locked = row.pop("LOCKED", False)

                for k in extra_keys:
                    row.pop(k, None)

                record = Session_Race_Records.query.filter_by(
                    title_2=title_2, heat=heat, cid=cid
                ).first()

                # Restore essential fields that were popped but are needed in the data JSON
                row["cid"] = int(cid)
                row["title_2"] = title_2
                row["heat"] = heat

                int_fields = ["finishtime", "penalty", "reaction", "inter_1", "inter_2", "inter_3", "speed", "laps", "points", "start_pos", "heat", "heats", "cid"]
                for field in int_fields:
                    if field in row and row[field] is not None and row[field] != "":
                        try:
                            row[field] = int(row[field])
                        except (ValueError, TypeError):
                            pass

                if record:
                    record.data = row
                    record.locked = bool(locked)

            db.session.commit()
            return jsonify({"status": "success"})

        # Form submission - pick event/heat
        else:
            use_active = request.form.get("event_file") == "active_event"

            if use_active:
                records = Session_Race_Records.query.filter_by(active_event=True).all()
                print(records)
                if not records:
                    return render_template(
                        "admin/active_events_driver_data.html",
                        unique_events=unique_events,
                        sqldata="None",
                        extra_keys=extra_keys,
                        dynamic_keys=[],
                        event_entry_file="None",
                        returned_event_info="No active event found",
                    )
                selected_event = records[0].title_2
                selected_heat = records[0].heat

            else:
                selected_event = request.form.get("event_name")
                run_val = request.form.get("run")
                
                if not run_val or not run_val.isdigit():
                    return render_template(
                        "admin/active_events_driver_data.html",
                        unique_events=unique_events,
                        sqldata="None",
                        extra_keys=extra_keys,
                        dynamic_keys=[],
                        event_entry_file="None",
                        returned_event_info="Please select a valid event and heat.",
                    )
                selected_heat = int(run_val)
                records = Session_Race_Records.query.filter_by(
                    title_2=selected_event, heat=selected_heat
                ).all()
            
            table_data = []
            for r in records:
                row = {
                    "CID": r.cid,
                    "LOCKED": r.locked,
                    "id": r.id,
                    "event_id": r.event_id,
                    "title_2": r.title_2,
                    "active_event": r.active_event,
                    "heat": r.heat,
                }
                if r.data:
                    row.update(r.data)
                table_data.append(row)
            
            print(table_data)
            # Extract dynamic column names from JSON data (exclude CID/LOCKED and extra_keys)
            dynamic_keys = []
            if table_data:
                for key in table_data[0]:
                    if key not in ("CID", "LOCKED") and key not in extra_keys:
                        dynamic_keys.append(key)

            event_info = f"{selected_event} - Heat: {selected_heat}"
            print("extra_k:", extra_keys)
            print("dyn_k:", dynamic_keys)
            return render_template(
                "admin/active_events_driver_data.html",
                unique_events=unique_events,
                sqldata=json.dumps(table_data),
                extra_keys=extra_keys,
                dynamic_keys=dynamic_keys,
                event_entry_file={"title_2": selected_event, "heat": selected_heat},
                returned_event_info=event_info,
            )

    return render_template(
        "admin/active_events_driver_data.html",
        unique_events=unique_events,
        sqldata="None",
        extra_keys=extra_keys,
        dynamic_keys=[],
        event_entry_file="None",
        returned_event_info="None",
    )

def msport_proxy():
    return render_template("pdfconverter.html")


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in {
        "png",
        "jpg",
        "jpeg",
        "gif",
    }


def infoscreen():
    from app import db
    from app.models import (
        InfoScreenInitMessage,
        GlobalConfig,
        InfoScreenAssets,
        InfoScreenAssetAssociations,
    )
    import html

    global_config = db.session.query(GlobalConfig).all()[0]
    full_asset_path = (
        global_config.project_dir[:-1] + global_config.infoscreen_asset_path
    )

    if request.method == "POST":
        content_type = request.content_type

        if content_type.startswith("multipart/form-data"):
            # Decode HTML entities in the form data
            name = html.unescape(request.form.get("name"))
            file = request.files.get("file")
            url = html.unescape(request.form.get("url"))

            check_name = InfoScreenAssets.query.filter_by(name=name).first()

            if file and allowed_file(file.filename):
                check_asset = InfoScreenAssets.query.filter_by(
                    asset=file.filename
                ).first()

                if check_asset is not None or check_name is not None:
                    print("Asset already exists")
                    return "Asset already exists"

                new_message = InfoScreenAssets(name=name, asset=file.filename)
                db.session.add(new_message)
                db.session.commit()
                filename = secure_filename(file.filename)
                file.save(os.path.join(full_asset_path, filename))
            elif url:
                check_asset = InfoScreenAssets.query.filter_by(asset=url).first()

                if check_asset is not None or check_name is not None:
                    print("Asset already exists")
                    return "Asset already exists"

                new_message = InfoScreenAssets(name=name, asset=url)
                db.session.add(new_message)
                db.session.commit()

                return "File uploaded successfully"

            if url:
                return "URL saved successfully"
            return "No valid asset provided"
        if request.get_json()["operation"] == 1:
            id = request.get_json()["id"]

            if request.get_json()["action"] == "approve":
                query = InfoScreenInitMessage.query.filter_by(unique_id=id).update(
                    {"approved": True}
                )

            elif request.get_json()["action"] == "remove":
                query = InfoScreenInitMessage.query.filter_by(unique_id=id)
                query.delete()

            elif request.get_json()["action"] == "deactivate":
                query = InfoScreenInitMessage.query.filter_by(unique_id=id).update(
                    {"approved": False}
                )

            elif request.get_json()["action"] == "delete":
                query = InfoScreenAssets.query.filter_by(id=id)
                asset_query = InfoScreenAssetAssociations.query.filter_by(asset=id)
                asset_query.delete()
                query.delete()
            db.session.commit()
            return {"OP": "Done"}

        elif request.get_json()["operation"] == 2:
            if request.get_json()["action"] == "add":
                data = request.get_json()
                if data["timer"] == "":
                    data["timer"] == 0
                new_message = InfoScreenAssetAssociations(
                    asset=data["selectedAsset"],
                    infoscreen=data["infoscreen"],
                    timer=data["timer"],
                )
                db.session.add(new_message)
                db.session.commit()
        elif request.get_json()["operation"] == 3:
            data = request.get_json()
            infoscreen = data["messageID"]
            asset_query = InfoScreenAssetAssociations.query.filter_by(
                infoscreen=infoscreen
            )
            asset_query.delete()
            for a in request.get_json()["data"]:
                asset = InfoScreenAssets.query.filter_by(name=a["name"]).first()
                new_message = InfoScreenAssetAssociations(
                    asset=asset.id, infoscreen=infoscreen, timer=a["timer"]
                )
                db.session.add(new_message)
            db.session.commit()
            print(infoscreen, "asdasd")
            update_info_screen(infoscreen)

        return {"OP": "None"}

    info_screen_msg = InfoScreenInitMessage.query.all()
    info_screen_assents = InfoScreenAssets.query.all()
    info_screen_associations = InfoScreenAssetAssociations.query.all()

    info_screen_assents_list = [
        {c.name: getattr(assent, c.name) for c in InfoScreenAssets.__table__.columns}
        for assent in info_screen_assents
    ]
    info_screen_assents_json = json.dumps(info_screen_assents_list, default=str)
    info_screen_approved = InfoScreenInitMessage.query.filter_by(approved=True).all()

    return render_template(
        "admin/infoscreen.html",
        info_screen_msg=info_screen_msg,
        info_screen_approved=info_screen_approved,
        info_screen_assents_json=info_screen_assents_json,
        info_screen_assents=info_screen_assents,
        info_screen_associations=info_screen_associations,
    )


def export_data():
    from app.models import ActiveEvents, GlobalConfig, LockedEntry, archive_server
    from app import db

    if request.method == "POST":
        content_type = request.content_type

        if content_type.startswith("application/json"):
            if request.get_json()["action"] == "config":
                archive_params = archive_server.query.first()
                if archive_params == None:
                    archive_params = archive_server(
                        hostname=request.get_json()["endpoint_url"],
                        auth_token=request.get_json()["auth_token"],
                        use_use_token=request.get_json()["use_auth_token"],
                    )
                    db.session.add(archive_params)
                    db.session.commit()
                else:
                    archive_params.hostname = request.get_json()["endpoint_url"]
                    archive_params.auth_token = request.get_json()["auth_token"]
                    archive_params.use_use_token = request.get_json()["use_auth_token"]
                    db.session.commit()
                return {"Success": "Updated configuration"}

    archive_params = archive_server.query.first()

    if archive_params == None:
        status = "2"
        current_driver = None
        archive_params_state = None
    else:
        archive_params_state = {
            "hostname": archive_params.hostname,
            "auth_token": archive_params.auth_token,
            "use_token": archive_params.use_use_token,
        }

        try:
            response = requests.get(archive_params.hostname + "/get_drivers")
            current_driver = response.json()
            status = "0"
        except:
            current_driver = "None"
            status = "1"

    event_export = export_events()
    return render_template(
        "admin/export.html",
        current_events=event_export,
        current_driver=current_driver,
        archive_params_state=archive_params_state,
        status=status,
    )


def clock_mgnt():
    from flask import Markup, current_app
    from app.models import GlobalConfig
    from app import db

    global_config = db.session.query(GlobalConfig).first()

    if request.method == "POST":
        data = request.get_json()
        global_config.auto_commit_manual_clock = bool(data.get("autoCommit"))
        global_config.dual_start_manual_clock = bool(data.get("duelStart"))
        db.session.commit()
        return "Updates"

    toggles = {
        "AutoCommit": global_config.auto_commit_manual_clock,
        "DualStart": global_config.dual_start_manual_clock,
    }

    current_timestamps = current_app.config["timestamp_tracket"]

    event_data_json = Markup(json.dumps(current_timestamps))

    return render_template(
        "admin/clock_mgnt.html", event_data=event_data_json, toggles=toggles
    )


def timekeeperpage():
    return render_template("admin/timekeeperpage.html")


def led_panel():
    from app.models import ledpanel
    from app import db

    def clear_display(endpoint):
        try:
            requests.get(f"http://{endpoint}:5000/stop", timeout=2)
        except Exception:
            pass
        try:
            requests.get(f"http://{endpoint}/api/overlays/model/LED%20Panels/clear", timeout=2)
        except Exception:
            pass
        try:
            requests.get(f"http://{endpoint}/api/playlists/stop", timeout=2)
        except Exception:
            pass

    def enable_display(endpoint):
        try:
            data = requests.get(
                f"http://{endpoint}/api/overlays/model/LED%20Panels/state", timeout=2
            )
            data = data.json()
            if data.get("isActive") == 0:
                requests.put(
                    f"http://{endpoint}/api/overlays/model/LED%20Panels/state",
                    json={"State": 1},
                    headers={"Content-Type": "application/json"},
                    timeout=2,
                )
        except Exception:
            pass

    if request.method == "POST":
        cmd = request.json.get("command")

        if cmd == "save_endpoint":
            endpoint = request.json["endpoint"]
            entry_id = request.json["panel_id"]
            db.session.query(ledpanel).filter_by(id=entry_id).update({"endpoint": endpoint})
            db.session.commit()
            return json.dumps({"success": True, "message": "Endpoint saved"}), 200

        elif cmd == "set_mode":
            panel_id = request.json["panel_id"]
            mode = request.json.get("mode", "off")
            mqtt_topic = request.json.get("mqtt_topic", "")
            font_size = request.json.get("font_size", 60)

            panel = ledpanel.query.get(panel_id)
            if not panel:
                return json.dumps({"success": False, "message": "Panel not found"}), 404

            panel.active_mode = mode
            if mqtt_topic:
                panel.mqtt_subscribe_topic = mqtt_topic
            db.session.commit()

            # Forward to FPP device
            try:
                requests.post(
                    f"http://{panel.endpoint}:5000/set_mode",
                    json={"mode": mode, "mqtt_topic": mqtt_topic, "font_size": int(font_size)},
                    timeout=3,
                )
            except requests.RequestException as e:
                print(f"Failed to send mode to {panel.endpoint}: {e}")

            return json.dumps({"success": True, "message": f"Mode set to {mode}"}), 200

        elif cmd == "set_brightness":
            panel_id = request.json["panel_id"]
            brightness = int(request.json.get("brightness", 100))

            panel = ledpanel.query.get(panel_id)
            if not panel:
                return json.dumps({"success": False, "message": "Panel not found"}), 404

            panel.brightness = brightness
            db.session.commit()

            # Forward to FPP device
            try:
                requests.post(
                    f"http://{panel.endpoint}:5000/set_brightness",
                    json={"brightness": brightness},
                    timeout=3,
                )
            except requests.RequestException as e:
                print(f"Failed to send brightness to {panel.endpoint}: {e}")

            return json.dumps({"success": True, "message": "Brightness updated"}), 200

        elif cmd == "set_flag_colors":
            panel_id = request.json["panel_id"]
            flag_colors = request.json.get("flag_colors", {})
            flag_priorities = request.json.get("flag_priorities", [])
            flag_enabled = request.json.get("flag_enabled", False)
            flag_fields_enabled = request.json.get("flag_fields_enabled", {})

            panel = ledpanel.query.get(panel_id)
            if not panel:
                return json.dumps({"success": False, "message": "Panel not found"}), 404

            panel.flag_colors = flag_colors
            panel.flag_priorities = flag_priorities
            panel.flag_enabled = flag_enabled
            panel.flag_fields_enabled = flag_fields_enabled
            db.session.commit()

            # Forward to FPP device
            try:
                requests.post(
                    f"http://{panel.endpoint}:5000/update_config",
                    json={
                        "flag_colors": flag_colors,
                        "flag_priorities": flag_priorities,
                        "flag_enabled": flag_enabled,
                        "flag_fields_enabled": flag_fields_enabled,
                    },
                    timeout=3,
                )
            except requests.RequestException as e:
                print(f"Failed to send flag config to {panel.endpoint}: {e}")

            return json.dumps({"success": True, "message": "Flag colors updated"}), 200

        elif cmd == "set_playlist":
            endpoint = request.json["endpoint"]
            args = request.json["args"]
            clear_display(endpoint)
            try:
                response = requests.post(
                    f"http://{endpoint}/api/command",
                    json={"command": "Start Playlist At Item", "args": args},
                    timeout=3,
                )
                response.raise_for_status()
                return json.dumps({"success": True, "message": "Playlist started"}), 200
            except requests.RequestException as e:
                return json.dumps({"success": False, "message": str(e)}), 500

        elif cmd == "display_text":
            endpoint = request.json["endpoint"]
            clear_display(endpoint)
            enable_display(endpoint)

            payload = json.dumps({
                "Message": request.json["Message"],
                "Position": "center",
                "Font": "Helvetica",
                "FontSize": request.json.get("FontSize", 60),
                "AntiAlias": False,
                "PixelsPerSecond": 20,
                "Color": request.json.get("Color", "#FFFFFF"),
                "AutoEnable": True,
            })
            try:
                response = requests.put(
                    f"http://{endpoint}/api/overlays/model/LED Panels/text",
                    headers={"Content-Type": "application/json"},
                    data=payload,
                    timeout=3,
                )
                response.raise_for_status()
                return json.dumps({"success": True, "message": "Text displayed"}), 200
            except requests.RequestException as e:
                return json.dumps({"success": False, "message": str(e)}), 500

        elif cmd == "stop":
            endpoint = request.json["endpoint"]
            panel_id = request.json.get("panel_id")
            clear_display(endpoint)

            # Update DB mode to off
            if panel_id:
                panel = ledpanel.query.get(panel_id)
                if panel:
                    panel.active_mode = "off"
                    db.session.commit()

            return json.dumps({"success": True, "message": "Display stopped"}), 200

        else:
            return json.dumps({"success": False, "message": "Unknown command"}), 400

    else:
        ledpanel_db = db.session.query(ledpanel).all()
        panels = {}
        for b in ledpanel_db:
            panels[b.id] = {
                'endpoint': b.endpoint,
                'brightness': b.brightness or 100,
                'active_mode': b.active_mode or 'off',
                'mqtt_subscribe_topic': b.mqtt_subscribe_topic or '',
                'flag_enabled': b.flag_enabled or False,
                'flag_colors': b.flag_colors or {},
                'flag_priorities': b.flag_priorities or [],
                'flag_fields_enabled': b.flag_fields_enabled or {
                    "halt_race": True, "warmup": True, "running": True,
                    "ready": True, "started": True, "orbits_finish": True,
                    "orbits_warmup": True, "man_ready": True
                },
                'active_playlist': b.active_playlist,
            }

        panels_json = json.dumps(panels)
        return render_template("admin/ledpanel.html", panels=panels, panels_json=panels_json)


def stream_overlay():
    return render_template("admin/overlay_editor.html")


def race_results():
    return render_template("admin/race_results.html", active_tab="race_results")
