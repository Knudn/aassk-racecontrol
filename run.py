from app import create_app, db, socketio  # Notice the added socketio import
from app.models import GlobalConfig, ActiveDrivers, SpeakerPageSettings, InfoScreenAssets, MicroServices, CrossConfig, ledpanel, archive_server
from app.lib.db_operation import update_active_event
import os
import logging
from logging.handlers import RotatingFileHandler
from app.lib.utils import GetEnv, is_screen_session_running, manage_process_screen, fifo_monitor
import socket
import argparse

pwd = os.getcwd()


# In-memory timestamp request tracker
virtual_clock_request = [
]

def configure_logging(app):
    log_level = logging.INFO 
    log_directory = os.path.join(os.getcwd(), 'logs')
    if not os.path.exists(log_directory):
        os.makedirs(log_directory)
    log_file = os.path.join(log_directory, 'app.log')

    handler = RotatingFileHandler(log_file, maxBytes=10000000, backupCount=5)
    formatter = logging.Formatter('[%(asctime)s] %(levelname)s in %(module)s: %(message)s')
    handler.setFormatter(formatter)

    app.logger.addHandler(handler)
    app.logger.setLevel(log_level)

    # Also log to stdout
    logging.basicConfig(level=log_level, format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s')
    

def create_tables(app):

    with app.app_context():
        db.create_all() 

        GlobalConfig_db = GlobalConfig.query.get(1)
        ActiveDrivers_db = ActiveDrivers.query.get(1)
        SpeakerPageSettings_db = SpeakerPageSettings.query.get(1)
        InfoScreenAssets_db = InfoScreenAssets.query.get(1)
        Cross_db = CrossConfig.query.all()
        MicroServices_db = MicroServices.query.all()
        ledpanel_db = ledpanel.query.all()
        archive_server_db = archive_server.query.all()

        if archive_server_db == []:
            default_config = archive_server(
                hostname = "192.168.20.218:5000",
                auth_token = "1234",
                use_use_token = True,
                state = False,
                enabled = False
            )

            db.session.add(default_config)
            db.session.commit()

        # If the database do not exist, it will be created here
        if GlobalConfig_db is None:
            app.logger.info('Created default global config')
            default_config = GlobalConfig(
                session_name = "Åseral",
                project_dir = pwd+"/",
                db_location = pwd+"/data/event_db/",
                event_dir = "/mnt/test/",
                wl_title = "Eikerapen",
                infoscreen_asset_path="/app/static/assets/infoscreen",
                intermediate_path="/mnt/intermediate/",
                hard_event_dir="/mnt/test/",
                autocommit=True,
                use_intermediate=True
            )
            db.session.add(default_config)
            db.session.commit()

        if SpeakerPageSettings_db is None:
            app.logger.info('Configuring DB for SpeakerPageSettings')
            default_config = SpeakerPageSettings(
                match_parrallel = False,
            )
            db.session.add(default_config)
            db.session.commit()

        if ledpanel_db == []:
            app.logger.info('Configuring DB for Ledpanel')
            panels = [
                ["192.168.20.219","none",100],
                ["192.168.20.220","none",100],
            ]
            for a in panels:
                new_entry = ledpanel(
                    endpoint = a[0],
                    active_playlist = a[1],
                    brightness = a[2]
                )
                db.session.add(new_entry)
            db.session.commit()
        if Cross_db == []:
            app.logger.info('Configuring DB for Cross Config')
            default_config = CrossConfig()
            db.session.add(default_config)
            db.session.commit()

        if MicroServices_db == []:
            app.logger.info('MicroService DB init')
            services = [
                ["Msport Proxy", "msport_display_proxy.py", "{0}".format(args.host)],
                ["Cross Clock Server", "cross_clock_server.py"],
                ["Backup Clock", "clock_server_vola.py", "192.168.1.51"],
                ["PDF Converter", "pdf_converter.py"],
                ["Intermediate Listener", "intermediate_list.py"]
            ]
            
            for a in services:

                if len(a) < 3:
                    a.append("None")

                new_entry = MicroServices(
                    name = a[0],
                    path = a[1],
                    params = a[2],
                )
                db.session.add(new_entry)
                manage_process_screen(a[1], "start")
            db.session.commit()
        else:
            for service in MicroServices_db:
                if bool(service.state) == True:
                    print(service.path)
                    manage_process_screen(service.path, "start")
                else: 
                    manage_process_screen(service.path, "stop")

        if InfoScreenAssets_db is None:
            app.logger.info('Infoscreen DB init')
            assets = [
                ["Ladder Active", "http://{0}:7777/board/ladder".format(IP)],
                ["Ladder loop 8", "http://{0}:7777/board/ladder/loop?timer=8".format(IP)],
                ["Ladder loop 15", "http://{0}:7777/board/ladder/loop?timer=15".format(IP)],
                ["Startlist active upcoming", "http://{0}:7777/board/startlist_simple_upcoming".format(IP)],
                ["Startlist active", "http://{0}:7777/board/startlist_simple".format(IP)],
                ["Startlist loop stige 8", "http://{0}:7777/board/startlist_simple_loop?event_filter=Stige&timer=8".format(IP)],
                ["Startlist loop stige 15", "http://{0}:7777/board/startlist_simple_loop?event_filter=Stige&timer=15".format(IP)],
                ["Startlist loop kval 8", "http://{0}:7777/board/startlist_simple_loop?event_filter=Kvalifisering&timer=8".format(IP)],
                ["Startlist loop kval 15", "http://{0}:7777/board/startlist_simple_loop?event_filter=Kvalifisering&timer=15".format(IP)],
                ["Startlist loop finale 8", "http://{0}:7777/board/startlist_simple_loop_single?event_filter=Finale&timer=8".format(IP)],
                ["Startlist loop finale 15", "http://{0}:7777/board/startlist_simple_loop_single?event_filter=Finale&timer=15".format(IP)],
                ["Startlist Cross Active", "http://{0}:7777/board/startlist_active_simple_single".format(IP)],
                ["Startlist Cross Active Upcoming", "http://{0}:7777/board/startlist_active_simple_single?upcoming=true".format(IP)],                
                ["Scoreboard loop 8", "http://{0}:7777/board/scoreboard_c?columns=3&timer=8".format(IP)],
                ["Scoreboard loop 15", "http://{0}:7777/board/scoreboard_c?columns=3&timer=15".format(IP)],
                ["Scoreboard cross all", "http://{0}:7777/board/scoreboard_cross?all=all".format(IP)],
                ["Scoreboard cross event", "http://{0}:7777/board/scoreboard_cross?active=true".format(IP)],
            ]
            for a in assets:
                new_entry = InfoScreenAssets(
                    name = a[0],
                    asset = a[1]
                )
                db.session.add(new_entry)
            db.session.commit()

        #GlobalConfig_db = GetEnv()

        try:
            active_event,active_heat = update_active_event(GlobalConfig_db)
        except:
            print("Could not get active event")
            active_event = 000
            active_heat = 0

        if ActiveDrivers_db is None:
            default_config = ActiveDrivers(
                D1 = 0,
                D2 = 0,
                Event = active_event,
                Heat = active_heat
            )
            
            db.session.add(default_config)
            db.session.commit()

        return GlobalConfig_db

if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='Run the web server with spesific host.')
    parser.add_argument('--host', type=str, default='0.0.0.0',
                            help='Host address to listen on. Default is 0.0.0.0.')

    args = parser.parse_args()
    IP = args.host 
    app, socketio = create_app()
    app.config['timestamp_tracket'] = virtual_clock_request
    app.config['listen_address'] = IP
    app.config['current_event'] = None
    app.config['event_content'] = ""
    app.config['remote_result_page_state'] = False
    app.config['remote_result_page_enabled'] = False
    
    configure_logging(app)
    app.logger.info('App started')
    create_tables(app)
    socketio.run(app, debug=True, host=args.host, port=7777)