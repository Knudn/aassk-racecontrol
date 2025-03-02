from app import create_app, db, socketio
from app.models import GlobalConfig, ActiveDrivers, SpeakerPageSettings, InfoScreenAssets, MicroServices, CrossConfig, ledpanel, archive_server
from app.lib.db_operation import update_active_event
import os
import logging
from logging.handlers import RotatingFileHandler
from app.lib.utils import GetEnv, is_screen_session_running, manage_process_screen, fifo_monitor
import socket
import argparse
import config

# In-memory timestamp request tracker
virtual_clock_request = []

def configure_logging(app):
    if not os.path.exists(config.LOG_DIRECTORY):
        os.makedirs(config.LOG_DIRECTORY)
    
    handler = RotatingFileHandler(
        config.LOG_FILE, 
        maxBytes=config.LOG_MAX_BYTES, 
        backupCount=config.LOG_BACKUP_COUNT
    )
    formatter = logging.Formatter(config.LOG_FORMAT)
    handler.setFormatter(formatter)

    app.logger.addHandler(handler)
    app.logger.setLevel(getattr(logging, config.LOG_LEVEL))

    # Also log to stdout
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL), 
        format=config.LOG_FORMAT
    )

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

        # Initialize archive server config if it doesn't exist
        if archive_server_db == []:
            app.logger.info('Configuring DB for Archive Server')
            default_config = archive_server(
                hostname=config.DEFAULT_ARCHIVE_SERVER["hostname"],
                auth_token=config.DEFAULT_ARCHIVE_SERVER["auth_token"],
                use_use_token=config.DEFAULT_ARCHIVE_SERVER["use_use_token"],
                state=config.DEFAULT_ARCHIVE_SERVER["state"],
                enabled=config.DEFAULT_ARCHIVE_SERVER["enabled"]
            )
            db.session.add(default_config)
            db.session.commit()

        # Initialize global config if it doesn't exist
        if GlobalConfig_db is None:
            app.logger.info('Created default global config')
            default_config = GlobalConfig(**config.DEFAULT_GLOBAL_CONFIG)
            db.session.add(default_config)
            db.session.commit()

        # Initialize speaker page settings if they don't exist
        if SpeakerPageSettings_db is None:
            app.logger.info('Configuring DB for SpeakerPageSettings')
            default_config = SpeakerPageSettings(**config.DEFAULT_SPEAKER_PAGE_SETTINGS)
            db.session.add(default_config)
            db.session.commit()

        # Initialize LED panels if they don't exist
        if ledpanel_db == []:
            app.logger.info('Configuring DB for Ledpanel')
            for panel_config in config.DEFAULT_LED_PANELS:
                new_entry = ledpanel(**panel_config)
                db.session.add(new_entry)
            db.session.commit()

        # Initialize cross config if it doesn't exist
        if Cross_db == []:
            app.logger.info('Configuring DB for Cross Config')
            default_config = CrossConfig()
            db.session.add(default_config)
            db.session.commit()

        # Initialize microservices if they don't exist
        if MicroServices_db == []:
            app.logger.info('MicroService DB init')
            
            for service_config in config.DEFAULT_MICROSERVICES:
                # Replace {host} placeholder with actual host value
                params = service_config["params"].replace("{host}", args.host)
                
                new_entry = MicroServices(
                    name=service_config["name"],
                    path=service_config["path"],
                    params=params
                )
                db.session.add(new_entry)
                manage_process_screen(service_config["path"], "start")
            db.session.commit()
        else:
            for service in MicroServices_db:
                if bool(service.state) == True:
                    print(service.path)
                    manage_process_screen(service.path, "start")
                else: 
                    manage_process_screen(service.path, "stop")

        # Initialize infoscreen assets if they don't exist
        if InfoScreenAssets_db is None:
            app.logger.info('Infoscreen DB init')
            for asset_config in config.INFOSCREEN_ASSETS:
                # Replace {ip} placeholder with actual IP
                asset_url = asset_config["asset"].replace("{ip}", IP)
                
                new_entry = InfoScreenAssets(
                    name=asset_config["name"],
                    asset=asset_url
                )
                db.session.add(new_entry)
            db.session.commit()

        try:
            active_event, active_heat = update_active_event(GlobalConfig_db)
        except:
            print("Could not get active event")
            active_event = 000
            active_heat = 0

        # Initialize active drivers if they don't exist
        if ActiveDrivers_db is None:
            default_config = ActiveDrivers(
                D1=0,
                D2=0,
                Event=active_event,
                Heat=active_heat
            )
            
            db.session.add(default_config)
            db.session.commit()

        return GlobalConfig_db

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Run the web server with specific host.')
    parser.add_argument('--host', type=str, default=config.DEFAULT_HOST,
                        help=f'Host address to listen on. Default is {config.DEFAULT_HOST}.')

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
    socketio.run(app, debug=config.DEBUG, host=args.host, port=config.PORT)