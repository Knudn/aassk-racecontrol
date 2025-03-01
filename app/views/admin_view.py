
from flask import Blueprint, render_template, request, url_for, redirect, flash
from app.lib.db_operation import *
from app.lib.utils import GetEnv, intel_sort, update_info_screen, export_events
import json
from werkzeug.utils import secure_filename
import requests


admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/admin/', methods=['GET'])
def admin_home():
    return home_tab()

@admin_bp.route('/admin/<string:tab_name>', methods=['GET','POST'])
def admin(tab_name):
    if tab_name == 'home':
        return home_tab()
    elif tab_name == 'global-config':
        return global_config_tab()
    elif tab_name == 's_set_active_driver':
        return s_set_active_driver()
    elif tab_name == 'cross_config':
        return cross_config_tab()
    elif tab_name == 'infoscreen':
        return infoscreen()
    elif tab_name == 'active_events':
        return active_events()
    elif tab_name == 'active_events_driver_data':
        return active_events_driver_data()
    elif tab_name == 'msport_proxy':
        return msport_proxy()
    elif tab_name == 'export':
        return export_data()
    elif tab_name == 'clock_mgnt':
        return clock_mgnt()
    elif tab_name == 'time_keeper':
        return timekeeperpage()
    elif tab_name == 'ledpanel':
        return led_panel()
    elif tab_name == 'kvali_criteria':
        return kvali_criteria()
    else:
        return "Invalid tab", 404



def s_set_active_driver():
    from flask import current_app
    list_address = current_app.config['listen_address']

    DB_PATH = "site.db"
    if request.method == "POST":
        active_driver_id = request.json["driverId"]
        with sqlite3.connect(DB_PATH) as con:
            cur = con.cursor()
            cur.execute("UPDATE active_drivers SET D1 = ?;", (active_driver_id,))
            print(cur.execute("SELECT * FROM active_drivers").fetchall())

        requests.get("http://{0}:7777/api/active_event_update".format(list_address))

        con.commit()
        return {"synced":"True"}

    return render_template('admin/s_set_active_driver.html') 

def home_tab():
    from app.models import ActiveDrivers, ActiveEvents, Session_Race_Records, GlobalConfig, MicroServices, archive_server
    from app import db
    from sqlalchemy import func
    import json

    archive_params = archive_server.query.first()

    archive_params_json = {"password": archive_params.auth_token, "hostname": archive_params.hostname, "enabled": archive_params.enabled}

    g_conf = db.session.query(GlobalConfig.db_location, GlobalConfig.event_dir, GlobalConfig.use_intermediate, GlobalConfig.intermediate_path).all()[0]

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
    enabled_events = (ActiveEvents.query
                        .filter(ActiveEvents.enabled == 1)
                        .group_by(ActiveEvents.event_name)
                        .with_entities(ActiveEvents.event_name, func.count(ActiveEvents.event_name))
                        .count())

    drivers = (Session_Race_Records.query
                      .with_entities(Session_Race_Records.first_name, Session_Race_Records.last_name)
                      .group_by(Session_Race_Records.first_name, Session_Race_Records.last_name)
                      .count())

    services = (MicroServices.query.all())
    

    number_runs = (ActiveEvents.query.filter(ActiveEvents.enabled == 1).count())

    unique_events = (
        db.session.query(
            ActiveEvents.event_name,
            func.max(ActiveEvents.run).label('max_run'),
            ActiveEvents.event_file
        )
        .group_by(ActiveEvents.event_name).order_by(ActiveEvents.sort_order)
        .all()
    )

    if request.method == "POST":

        if "endpoint_server_update" in request.form:

            hostname = request.form.get('hostname')
            password = request.form.get('password')
            state = request.form.get('state')

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

            return {"Success":"Updated configuration"}
        
        elif "single_event" in request.form:
            
            if request.form.get('event_file') == "active_event":
                active_event = get_active_event()
                selectedEventFile = active_event[0]["db_file"]
                selectedRun = active_event[0]["SPESIFIC_HEAT"]
            else:
                selectedEventFile = request.form.get('single_event')
                
                sync_state = request.form.get('sync')

            if sync_state == "true":
                from app.lib.utils import GetEnv
                g_config = GetEnv()

                event_name = request.form.get('event_name')

                #Delete local driver session entries for the spesific event
                db.session.query(Session_Race_Records).filter((Session_Race_Records.title_1 + " " + Session_Race_Records.title_2)==event_name).delete()
                db.session.commit()
                print(selectedEventFile)
                full_db_reload(add_intel_sort=False, Event=selectedEventFile)


            print("Getting:", selectedEventFile)

            with sqlite3.connect(db_location + selectedEventFile + ".sqlite") as con:
                cur = con.cursor()
                cur.execute(f"SELECT COUNT() FROM drivers;")
                amount_drivers = cur.fetchone()
                cur.execute(f"SELECT COUNT() FROM sqlite_master WHERE type='table' AND name LIKE 'driver\_%' ESCAPE '\\';")
                heat_num = cur.fetchone()[0]
                valid_recorded_times = 0
                invalid_recorded_times = 0
                drivers_left = 0
 
                for a in range(1,heat_num+1):
                    cur.execute("SELECT COUNT() FROM driver_stats_r{0} WHERE FINISHTIME != 0 AND PENELTY = 0;".format(a))
                    valid_recorded_times += cur.fetchone()[0]

                    cur.execute("SELECT COUNT() FROM driver_stats_r{0} WHERE PENELTY != 0;".format(a))
                    invalid_recorded_times += cur.fetchone()[0]

                    cur.execute("SELECT COUNT() FROM driver_stats_r{0} WHERE FINISHTIME = 0 AND PENELTY = 0;".format(a))
                    drivers_left += cur.fetchone()[0]

                event_config = {"all_records":(valid_recorded_times + invalid_recorded_times + drivers_left), "p_times":invalid_recorded_times, "v_times":valid_recorded_times, "l_times":drivers_left, "drivers":amount_drivers, "heats":heat_num}
                return event_config
            
        elif "service_state" in request.form:
            from app.lib.utils import GetEnv, is_screen_session_running, manage_process_screen
            
            from time import sleep

            service_name = request.form.get('service_name')
            service_state = request.form.get('service_state')
            params = request.form.get('ip_address')

            if service_name == None:
                return "None"

            service_object = db.session.query(MicroServices).filter((MicroServices.name == service_name)).first()
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


    return render_template('admin/index.html', drivercount=drivers, num_run=number_runs, num_events=enabled_events, events=unique_events, microservices=services, mount_bool=mount_bool, mount_path=mount_path,  archive_params_json=archive_params_json)

def kvali_criteria():
    from app.models import EventKvaliRate
    from app import db

    
    if request.method == 'POST':
        data = request.get_json()
        EventKvaliRate.query.delete()
        data_len = len(data)

        for k, a in enumerate(dict(data).keys()):
            kvali_num = data[a]
            new_entry = EventKvaliRate(
                id= k+1,
                event = a,
                kvalinr = int(kvali_num)
            )
            db.session.add(new_entry)
        db.session.commit()
        return {"Success": "True"}

    else:
        kvali_criteria = [event.to_dict() for event in EventKvaliRate.query.all()]
        return render_template('admin/kval_criteria.html', kvali_criteria=kvali_criteria)


def cross_config_tab():
    from app.models import CrossConfig, db
    from flask import Markup


    cross_config = CrossConfig.query.first()

    if request.method == 'POST':

        # Extract form data
        dnf_point = request.form.get('dnf_point', type=int)
        dns_point = request.form.get('dns_point', type=int)
        dsq_point = request.form.get('dsq_point', type=int)
        invert_score = request.form.get('invert_score') == 'true'
        num_drivers = request.form.get('num_drivers', type=int)
        
        # Prepare driver_scores dictionary
        driver_scores = {}
        for i in range(1, num_drivers + 1):
            score = request.form.get(f'driver_scores[{i}]', type=int)
            if score is not None:
                driver_scores[i] = score

        # If there's no existing config, create a new one
        if not cross_config:
            cross_config = CrossConfig()

        # Update cross_config with form values
        cross_config.dnf_point = dnf_point
        cross_config.dns_point = dns_point
        cross_config.dsq_point = dsq_point
        cross_config.invert_score = invert_score
        cross_config.driver_scores = driver_scores

        # Add to session and commit if new, otherwise just commit the changes
        if not CrossConfig.query.first():
            db.session.add(cross_config)
        db.session.commit()


        # Redirect to avoid form resubmission issues
        return redirect(url_for('admin.admin', tab_name='cross_config'))

    # Render template at the end of the function, passing the cross_config
    driver_scores_json = json.dumps(cross_config.driver_scores)
    return render_template('admin/cross_config_tab.html', cross_config=cross_config, driver_scores_json=driver_scores_json)

def global_config_tab():
    from app.models import GlobalConfig, ConfigForm, ActiveDrivers, Session_Race_Records, MicroServices, ActiveEvents
    from app import db
    from app.lib.utils import manage_process_screen
    from sqlalchemy import asc



    global_config = GlobalConfig.query.all()


    form = ConfigForm()
    
    if request.method == 'POST':
        if 'submit' in request.form:
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


                if bool(form.cross.data):
                    db.session.query(MicroServices).filter(MicroServices.name == "Cross Clock Server").update({"state": True})
                    db.session.commit()
                    manage_process_screen("cross_clock_server.py", "start")
                db.session.commit()
        elif 'update' in request.form: 
            print("asdasd")
        else:
            keep_previous_sort = global_config[0].keep_previous_sort

            if global_config[0].keep_previous_sort == True:
                ActiveEvents_entries = ActiveEvents.query.filter(ActiveEvents.id).order_by(asc(ActiveEvents.sort_order)).all()
                ActiveEvents_list = []
                for h in ActiveEvents_entries:
                    ActiveEvents_list.append(h.id)

            db.session.query(Session_Race_Records).delete()
            full_db_reload(add_intel_sort=True)
            if global_config[0].keep_previous_sort == True:

                order_mapping = {id_value: index for index, id_value in enumerate(ActiveEvents_list)}
                events = ActiveEvents.query.filter(ActiveEvents.id.in_(ActiveEvents_list)).all()
                for event in events:

                    event.sort_order = order_mapping[event.id]
                    
                db.session.commit()
            
        return redirect(url_for('admin.admin', tab_name='global-config'))



    return render_template('admin/global_config.html', global_config=global_config, form=form)


def active_events():
    from app.models import ActiveEvents, EventType, EventOrder, GlobalConfig
    from app import db

    

    if request.method == 'POST':
        # Handle the form data for table updates
        table_data = request.form.get('table_data')
        sort_data = request.form.get('eventOrderJson')

        # If table_data is provided, process it
        if table_data:
            try:
                table_data = json.loads(table_data)
                for k, row in enumerate(table_data):
                    k += 1
                    event = ActiveEvents.query.get(row['id'])
                    if event:
                        event.event_name = row['name']
                        event.run = row['run']
                        event.enabled = row['enable']
                        event.sort_order = k
                db.session.commit()
                flash('Active events updated successfully.', 'success')
            except Exception as e:
                db.session.rollback()  # Rollback in case of error
                flash(f'An error occurred: {e}', 'error')
        
        # If sort_data is provided, process it to update the sort order
        elif sort_data:
            
            try:
                EventType.query.delete()
                EventOrder.query.delete()
                # Insert EventTypes
                sort_data = json.loads(sort_data)
                for event_type in sort_data['eventTypes']:
                    new_event_type = EventType(
                        order=event_type['order'],
                        name=event_type['name'],
                        finish_heat=event_type['finishHeat']
                    )
                    db.session.add(new_event_type)
                
                # Insert EventOrders
                for event_order in sort_data['eventOrder']:
                    new_event_order = EventOrder(
                        order=event_order['order'],
                        name=event_order['name']
                    )
                    db.session.add(new_event_order)
                
                # Commit the session to save changes
                db.session.commit()
                
            except Exception as e:
                db.session.rollback()  # Rollback in case of error
                flash(f'An error occurred while updating the sort order: {e}', 'error')
            intel_sort()

        elif "smartSortingEnabled" in request.get_json():
            data = request.get_json()['smartSortingEnabled']
            global_config = GlobalConfig.query.first()
            global_config.Smart_Sorting = bool(data)
            db.session.commit()

            if bool(data) == False:
                active_events = ActiveEvents.query.all()

                # Update sort_order to match the id for each event
                for event in active_events:
                    event.sort_order = event.id

                # Commit the changes to the database
                db.session.commit()
                
        return redirect(url_for('admin.admin', tab_name='active_events'))

    # For GET requests or after POST processing, retrieve and display the active events
    active_events = ActiveEvents.query.order_by(ActiveEvents.sort_order).all()
    event_types = EventType.query.order_by(EventType.order).all()
    event_order = EventOrder.query.order_by(EventOrder.order).all()
    global_config_new = GlobalConfig.query.first()
    return render_template('admin/active_events.html', active_events=active_events, event_types=event_types, event_order=event_order, global_config_new=global_config_new)

def active_events_driver_data():
    from app.models import ActiveEvents, GlobalConfig, LockedEntry
    from app import db
    from sqlalchemy import func
    import sqlite3
    import time
    from app.lib.db_operation import get_active_event

    db_location = db.session.query(GlobalConfig.db_location).all()[0][0]

    unique_events = (
        db.session.query(
            ActiveEvents.event_name,
            func.max(ActiveEvents.run).label('max_run'),
            ActiveEvents.event_file
        )
        .group_by(ActiveEvents.event_name).order_by(ActiveEvents.sort_order)
        .all()
    )

    if request.method == 'POST':
        if request.form.get('event_file') is not None:
            if request.form.get('event_file') == "active_event":
                active_event = get_active_event()
                selectedEventFile = active_event[0]["db_file"]
                selectedRun = active_event[0]["SPESIFIC_HEAT"]
            else:
                selectedEventFile = request.form.get('event_file')
                selectedRun = request.form.get('run')
            event_entry_file_picked = {"file": selectedEventFile, "run": selectedRun}
            print("Getting:", selectedEventFile, selectedRun)
            with sqlite3.connect(db_location + selectedEventFile + ".sqlite") as con:
                cur = con.cursor()
                cur.execute(f"SELECT * FROM driver_stats_r{selectedRun}")

                data = [dict((cur.description[i][0], value) for i, value in enumerate(row)) for row in cur.fetchall()]
                cur.execute(f"SELECT TITLE1, TITLE2, MODE FROM db_index")
                event_title = cur.fetchall()
                event_info = event_title[0][0]+" "+event_title[0][1]+" - Heat: " + str(selectedRun)  + " - Mode: "+ str(event_title[0][2])

            return render_template('admin/active_events_driver_data.html', unique_events=unique_events, sqldata=data, event_entry_file=event_entry_file_picked, returned_event_info=event_info)

        else:
            data = request.get_json()
            file = data["file"]
            run = data["run"]

            db_location = db.session.query(GlobalConfig.db_location).all()[0][0]
            sql_con = sqlite3.connect(db_location + file + ".sqlite")
            sql_cur = sql_con.cursor()
            sql_cur.execute(f'DELETE FROM driver_stats_r{run}')

            for a in data["data"]:
                if "LOCKED" in a.keys() and a["LOCKED"] == True:
                    locked = "1"
                else:
                    locked = "0"
                sql_cur.execute(f'''
                    INSERT INTO driver_stats_r{run} (INTER_1, INTER_2, INTER_3, SPEED, PENELTY, FINISHTIME, CID, LOCKED)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                    (a['INTER_1'], a['INTER_2'], a['INTER_3'], a['SPEED'], a['PENELTY'], a['FINISHTIME'], int(a['CID']), locked)
                )  
            sql_con.commit()
            sql_con.close()
        
        return render_template('admin/active_events_driver_data.html', unique_events=unique_events, sqldata=data, event_entry_file="None")

    return render_template('admin/active_events_driver_data.html', unique_events=unique_events, sqldata="None", event_entry_file="None")

def msport_proxy():

    return render_template('pdfconverter.html')

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'gif'}


def infoscreen():
    from app import db
    from app.models import InfoScreenInitMessage, GlobalConfig, InfoScreenAssets, InfoScreenAssetAssociations
    import html

    global_config = db.session.query(GlobalConfig).all()[0]
    full_asset_path = global_config.project_dir[:-1] + global_config.infoscreen_asset_path

    if request.method == 'POST':
        
        content_type = request.content_type

        
        if content_type.startswith("multipart/form-data"):

            # Decode HTML entities in the form data
            name = html.unescape(request.form.get('name'))
            file = request.files.get('file')
            url = html.unescape(request.form.get('url'))
            
            check_name = InfoScreenAssets.query.filter_by(name=name).first()
            
            if file and allowed_file(file.filename):

                check_asset = InfoScreenAssets.query.filter_by(asset=file.filename).first()

                if check_asset is not None or check_name is not None:
                    print("Asset already exists")
                    return 'Asset already exists'
                
                new_message = InfoScreenAssets(name=name, asset=file.filename)
                db.session.add(new_message)
                db.session.commit()
                filename = secure_filename(file.filename)
                file.save(os.path.join(full_asset_path, filename))
            elif url:
                check_asset = InfoScreenAssets.query.filter_by(asset=url).first()

                if check_asset is not None or check_name is not None:
                    print("Asset already exists")
                    return 'Asset already exists'
                
                new_message = InfoScreenAssets(name=name, asset=url)
                db.session.add(new_message)
                db.session.commit()
                                
                return 'File uploaded successfully'
                
            if url:                
                return 'URL saved successfully'
            return 'No valid asset provided'
        print(request.get_json()["operation"])
        if request.get_json()["operation"] == 1:
            print("asd")
            id = request.get_json()["id"]
            
            if request.get_json()["action"] == "approve":
                query = InfoScreenInitMessage.query.filter_by(unique_id=id).update({"approved": True})

            elif request.get_json()["action"] == "remove":
                query = InfoScreenInitMessage.query.filter_by(unique_id=id)
                query.delete()

            elif request.get_json()["action"] == "deactivate":
                query = InfoScreenInitMessage.query.filter_by(unique_id=id).update({"approved": False})

            elif request.get_json()["action"] == "delete":
                query = InfoScreenAssets.query.filter_by(id=id)
                asset_query = InfoScreenAssetAssociations.query.filter_by(asset=id)
                asset_query.delete()
                query.delete()
            db.session.commit()
            return {"OP":"Done"}
        
        elif request.get_json()["operation"] == 2:
            if request.get_json()["action"] == "add":
                data = request.get_json()
                if data["timer"] == '':
                    data["timer"] == 0
                new_message = InfoScreenAssetAssociations(asset=data["selectedAsset"], infoscreen=data["infoscreen"], timer=data["timer"])
                db.session.add(new_message)
                db.session.commit()
        elif request.get_json()["operation"] == 3:
            data = request.get_json()
            infoscreen = data["messageID"]
            asset_query = InfoScreenAssetAssociations.query.filter_by(infoscreen=infoscreen)
            asset_query.delete()
            for a in request.get_json()["data"]:
                asset = InfoScreenAssets.query.filter_by(name=a["name"]).first()
                new_message = InfoScreenAssetAssociations(asset=asset.id, infoscreen=infoscreen, timer=a["timer"])
                db.session.add(new_message)
            db.session.commit()
            print(infoscreen, "asdasd")
            update_info_screen(infoscreen)

        return {"OP":"None"}

    
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
        'admin/infoscreen.html',
        info_screen_msg=info_screen_msg,
        info_screen_approved=info_screen_approved,
        info_screen_assents_json=info_screen_assents_json,
        info_screen_assents=info_screen_assents,
        info_screen_associations=info_screen_associations
    )

def export_data():
    from app.models import ActiveEvents, GlobalConfig, LockedEntry, archive_server
    from app import db
    
    if request.method == 'POST':
        content_type = request.content_type
        
        if content_type.startswith("application/json"):
            if request.get_json()["action"] == "config":
                archive_params = archive_server.query.first()
                if archive_params == None:
                    archive_params = archive_server(hostname=request.get_json()["endpoint_url"], auth_token=request.get_json()["auth_token"], use_use_token=request.get_json()["use_auth_token"])
                    db.session.add(archive_params)
                    db.session.commit()
                else:
                    archive_params.hostname = request.get_json()["endpoint_url"]
                    archive_params.auth_token = request.get_json()["auth_token"]
                    archive_params.use_use_token = request.get_json()["use_auth_token"]
                    db.session.commit()
                return {"Success":"Updated configuration"}

    archive_params = archive_server.query.first()
    

    if archive_params == None:
        status = "2"
        current_driver = None
        archive_params_state = None
    else:
        archive_params_state = {"hostname":archive_params.hostname, "auth_token":archive_params.auth_token, "use_token":archive_params.use_use_token}
        
        try:
            response = requests.get(archive_params.hostname+"/get_drivers")
            current_driver = response.json()
            status = "0"
        except:
            current_driver = "None"
            status = "1"
    
    
    event_export = export_events()
    return render_template('admin/export.html', current_events=event_export, current_driver=current_driver, archive_params_state=archive_params_state, status=status)

def clock_mgnt():
    from flask import Markup, current_app
    from app.models import GlobalConfig
    from app import db

    global_config = db.session.query(GlobalConfig).first()


    if request.method == 'POST':
        data = request.get_json()
        global_config.auto_commit_manual_clock = bool(data.get("autoCommit"))
        global_config.dual_start_manual_clock = bool(data.get("duelStart"))
        db.session.commit()
        return "Updates"

    toggles = {"AutoCommit":global_config.auto_commit_manual_clock, "DualStart":global_config.dual_start_manual_clock}


    current_timestamps = current_app.config['timestamp_tracket']
    
    event_data_json = Markup(json.dumps(current_timestamps))
    
    return render_template('admin/clock_mgnt.html', event_data=event_data_json, toggles=toggles)

def timekeeperpage():
    return render_template('admin/timekeeperpage.html')

def led_panel():
    from app.models import ledpanel
    from app import db


    def clear_display(endpoint):
        requests.get(f"http://{endpoint}:5000/stop")
        requests.get(f"http://{endpoint}/api/overlays/model/LED%20Panels/clear")
        requests.get(f"http://{endpoint}/api/playlists/stop")
        

    def enable_display(endpoint):

        data = requests.request("GET", "http://{0}/api/overlays/model/LED%20Panels/state".format(endpoint))
        data = json.loads(data.content)
        active_state = data["isActive"]
        if active_state == 0:
            url = "http://{0}/api/overlays/model/LED%20Panels/state".format(endpoint)

            headers = {
                "Accept": "*/*",
                "X-Requested-With": "XMLHttpRequest",
                "Accept-Language": "en-US",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.6478.127 Safari/537.36",
                "Content-Type": "application/json",
                "Origin": "http://192.168.20.219",
                "Referer": "http://192.168.20.219/plugin.php?_menu=status&plugin=fpp-matrixtools&page=matrixtools.php",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive"
            }

            data = {"State": 1}

            response = requests.put(url, json=data, headers=headers)

    if request.method == "POST":
        print(request.json["command"])

        if request.json["command"] == "save_endpoint":
            endpoint = request.json["endpoint"]
            entry_id = request.json["panel_id"]

            db.session.query(ledpanel).filter_by(id=entry_id).update({
                "endpoint": endpoint,
            })
            db.session.commit()
            return json.dumps({"success": True, "message": "Endpoint added successfully"}), 200

        elif request.json["command"] == "save_mode_config":
        
            ledpanel_db = db.session.query(ledpanel).all()

            if request.json["mode"] == "parallel":
                mode = 2
                for b in range(1, 3):
                    db.session.query(ledpanel).filter_by(id=b).update({
                        "track": request.json["display{0}_driver".format(str(b))],
                        "mode": mode,
                    })
                db.session.commit()
            else:
                mode = 1
                for b in range(1, 3):
                    db.session.query(ledpanel).filter_by(id=b).update({
                        "track": request.json["display"],
                        "mode": mode,
                        })
                db.session.commit()

            for a in ledpanel_db:
                if a.mode == 1:
                    mode = "single"
                else:
                    mode = "parallel"

                track = a.track

                config_data = {
                    "mode": mode,
                    "track": track
                }

                try:
                    response = requests.post(
                        "http://{0}:5000/update_config".format(a.endpoint),
                        json=config_data,
                        timeout=1.5,
                        headers={'Content-Type': 'application/json'}
                    )
                except requests.RequestException as e:
                    print("Failed to send config to {0}".format(a.endpoint))
                
            return json.dumps({"success": True, "message": "Mode updated successfully"}), 200



        elif request.json["command"] == "set_playlist":


            endpoint = request.json['endpoint']
            args = request.json['args']

            payload = {
                "command": "Start Playlist At Item",
                "args": args
            }

            clear_display(endpoint)
            
            try:

                response = requests.post(f"http://{endpoint}/api/command", json=payload)
                response.raise_for_status()
                return json.dumps({"success": True, "message": "Playlist started successfully"}), 200
            except requests.RequestException as e:
                return json.dumps({"success": False, "message": str(e)}), 500
                
        elif request.json["command"] == "edit_db_data":
            pass

        elif request.json["command"] == "display_text":

            endpoint = request.json["endpoint"]

            headers = {
                'Content-Type': 'application/json'
            }

            clear_display(endpoint)
            enable_display(endpoint)
        



            payload = request.json
            font_size = request.json["FontSize"]
            Color = request.json["Color"]
            Message = request.json["Message"]

            payload = json.dumps({
                "Message": Message,
                "Position": "center",
                "Font": "Helvetica",
                "FontSize": font_size,
                "AntiAlias": False,
                "PixelsPerSecond": 20,
                "Color": Color,
                "AutoEnable": True
                })


            try:

                response = requests.request("PUT", "http://{0}/api/overlays/model/LED Panels/text".format(endpoint), headers=headers, data=payload)

                response.raise_for_status()
                return json.dumps({"success": True, "message": "Playlist started successfully"}), 200

            except requests.RequestException as e:
                return json.dumps({"success": False, "message": str(e)}), 500

        elif request.json["command"] == "stop":
            endpoint = request.json["endpoint"]

            clear_display(endpoint)
            enable_display(endpoint)
        else:
            return json.dumps({"success": False, "message": str("asd")})

    else:

        ledpanel_db = db.session.query(ledpanel).all()
        panels = {}
        mode_config = {}
        for b in ledpanel_db:
            panels[b.id] = [b.endpoint, b.active_playlist, b.brightness, b.mode, b.track]
            if b.id == 1:
                if b.mode == 1:
                    mode_config["mode"] = "single"
                    mode_config["display"] = b.track

                else:
                    mode_config["mode"] = "parallel"

                mode_config["display1_driver"] = b.track
            else:
                mode_config["display2_driver"] = b.track

        print(mode_config)
        return render_template('admin/ledpanel.html', panels=panels, mode_config=mode_config)