from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, BooleanField, IntegerField
from sqlalchemy.dialects.postgresql import JSON
from datetime import datetime
from app import db

class InfoScreenInitMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    hostname = db.Column(db.String(128), nullable=False)
    ip = db.Column(db.String(15), nullable=False)
    unique_id = db.Column(db.String(32), nullable=False)
    approved = db.Column(db.String(6), nullable=False, default=False)

    def __repr__(self):
        return f'<InitMessage {self.hostname} {self.ip} {self.unique_id} {self.approved}>'

class SpeakerPageSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    match_parrallel = db.Column(db.Boolean, default=False)
    h_server_url = db.Column(db.String(128), default="http://192.168.20.218:5000")

    def __repr__(self):
        return f'<InitMessage {self.id} {self.match_parrallel} {self.h_server_url}>'

class archive_server(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    hostname = db.Column(db.String(128), nullable=False)
    auth_token = db.Column(db.String(128), nullable=False)
    use_use_token = db.Column(db.Boolean, default=False)
    state = db.Column(db.Boolean, default=False)
    enabled = db.Column(db.Boolean, default=False)
    
    def __repr__(self):
        return f'<archive_server {self.id} {self.hostname} {self.auth_token} {self.use_use_token}>'

class EventKvaliRate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event = db.Column(db.String(128), nullable=False)
    kvalinr = db.Column(db.Integer, primary_key=True)
    
    def __repr__(self):
        return f'<event_kvali_rate {self.id} {self.event} {self.kvalinr}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'event': self.event,
            'kvalinr': self.kvalinr
        }
    

class InfoScreenAssetAssociations(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    asset = db.Column(db.Integer, nullable=False)
    infoscreen = db.Column(db.Integer, nullable=False)
    timer = db.Column(db.Integer)
    options = db.Column(JSON, nullable=True)

    def __repr__(self):
        return f'<InitMessage {self.asset} {self.infoscreen} {self.timer} {self.options}>'
    
class InfoScreenAssets(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(32), nullable=False)
    asset = db.Column(db.String(256), nullable=False)

    def __repr__(self):
        return f'<InitMessage {self.asset} {self.name}>'

class ConfigForm(FlaskForm):
    session_name = StringField('Session Name')
    project_dir = StringField('Project Directory')
    db_location = StringField('Database Location')
    event_dir = StringField('Event Directory')
    wl_title = StringField('Whitelist Title')
    wl_cross_title = StringField('Whitelist Cross Title')
    exclude_title = StringField('Blacklist Title')
    wl_bool = BooleanField('Use Whitelist')
    keep_previous_sort = BooleanField('Keep previous event sort')
    keep_qualification = BooleanField('Keep previous qualification criteria?')
    display_proxy = BooleanField('Use MSport display proxy')
    cross = BooleanField('Watercross/Snowcross')
    submit = SubmitField('Save')

    intermediate_path = StringField('Whitelist Title')
    hard_event_dir = StringField('Whitelist Title')
    autocommit = BooleanField('Watercross/Snowcross')
    use_intermediate = BooleanField('Watercross/Snowcross')

    reload = SubmitField('Reload local DB')

class GlobalConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True, default=1)
    session_name = db.Column(db.String(100), nullable=True, default="Åseral")
    project_dir = db.Column(db.String(100), nullable=True, default="/home/rock/aassk/new_system")
    db_location = db.Column(db.String(100), nullable=True, default="/home/rock/aassk/new_system/event_db/")
    event_dir = db.Column(db.String(100), nullable=True, default="/mnt/test/")
    wl_title = db.Column(db.String(100), nullable=True, default="Watercross")
    infoscreen_asset_path = db.Column(db.String(128), nullable=True, default="/app/static/assets/infoscreen")
    wl_bool = db.Column(db.Boolean, default=True)
    cross = db.Column(db.Boolean, default=False)
    display_proxy = db.Column(db.Boolean, default=True)
    Smart_Sorting = db.Column(db.Boolean, default=False)
    keep_previous_sort = db.Column(db.Boolean, default=False)
    keep_qualification = db.Column(db.Boolean, default=False)
    wl_cross_title = db.Column(db.String(100), nullable=False, default="")
    exclude_title = db.Column(db.String(100), nullable=False, default="")
    auto_commit_manual_clock = db.Column(db.Boolean, default=False)
    dual_start_manual_clock = db.Column(db.Boolean, default=False)

    intermediate_path = db.Column(db.String(100), nullable=True, default="/mnt/intermediate/")
    hard_event_dir = db.Column(db.String(100), nullable=True, default="/mnt/test/")
    autocommit = db.Column(db.Boolean, default=False)
    use_intermediate = db.Column(db.Boolean, default=False)


class ActiveEvents(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    event_name = db.Column(db.String(100))
    event_file = db.Column(db.String(20))
    run = db.Column(db.Integer)
    enabled = db.Column(db.Integer, default=True)
    sort_order = db.Column(db.Integer)
    mode = db.Column(db.Integer)

    def __repr__(self):
        return (f"<ActiveEvents(id={self.id}, event_name='{self.event_name}', event_file='{self.event_file}', "
                f"run={self.run}, enabled={self.enabled}, sort_order={self.sort_order}, mode={self.mode})>")

class LockedEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    cid = db.Column(db.Integer)
    event_name = db.Column(db.String(100))
    heat = db.Column(db.Integer)

class ActiveDrivers(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    Event = db.Column(db.String(20))
    Heat = db.Column(db.String(20))
    D1 = db.Column(db.Integer)
    D2 = db.Column(db.Integer)

class EventType(db.Model):
    __tablename__ = 'event_types'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    order = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String, nullable=False)
    finish_heat = db.Column(db.Boolean, default=False, nullable=False)

    def __repr__(self):
        return f"<EventType(order={self.order}, name='{self.name}', finish_heat={self.finish_heat})>"

class EventOrder(db.Model):
    __tablename__ = 'event_order'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    order = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String, nullable=False)

    def __repr__(self):
        return f"<EventOrder(order={self.order}, name='{self.name}')>"
    
class Session_Race_Records(db.Model):
    __tablename__ = 'Active_Session_Race_Records'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    cid =  db.Column(db.Integer, nullable=True, default=55)
    first_name = db.Column(db.String(84), nullable=False)
    last_name = db.Column(db.String(84), nullable=False)
    title_1 = db.Column(db.String(84), nullable=False)
    title_2 = db.Column(db.String(84), nullable=False)
    heat = db.Column(db.Integer, nullable=False)
    finishtime = db.Column(db.Integer, nullable=False)
    snowmobile = db.Column(db.String(84), nullable=True)
    penalty = db.Column(db.Integer, nullable=False)
    points = db.Column(db.Integer, nullable=False, default=0)
    

class Session_Drivers(db.Model):
    __tablename__ = 'session_drivers'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    first_name = db.Column(db.String(84), nullable=False)
    last_name = db.Column(db.String(84), nullable=False)
    def __repr__(self):
        return f"<EventOrder(id={self.id}, first_name='{self.first_name}', last_name='{self.last_name}')>"

class MicroServices(db.Model):
    __tablename__ = 'microservices'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(64), nullable=False)
    path = db.Column(db.String(84), nullable=False)
    state = db.Column(db.Boolean, nullable=False, default=False)
    params = db.Column(db.String(84), nullable=True)
    def __repr__(self):
        return f"<Microservices(id={self.id}, name='{self.name}', state='{self.state}')>"

class CrossConfig(db.Model):
    __tablename__ = 'crossconfig'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    dnf_point = db.Column(db.Integer, nullable=False, default=0)
    dsq_point = db.Column(db.Integer, nullable=False, default=0)
    dns_point = db.Column(db.Integer, nullable=False, default=0)
    invert_score = db.Column(db.Boolean, nullable=False, default=False)

    #This dict will be used to also get the amount the drivers
    driver_scores = db.Column(db.JSON, nullable=True, default=lambda: {1: 8, 2: 16})
    
    def __repr__(self):
        return f"<CrossConfig(id={self.id}, dnf_point={self.dnf_point}, dsq_point={self.dsq_point}, dns_point={self.dns_point}, invert_score={self.invert_score}, driver_scores={self.driver_scores})>"

class RetryEntries(db.Model):
    __tablename__ = 'retryentries'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    cid = db.Column(db.Integer, nullable=True)
    title = db.Column(db.String(84), nullable=True)
    driver_name = db.Column(db.String(84), nullable=True)

    def __repr__(self):
        return f"<CrossConfig(id={self.id}, cid={self.cid}, title={self.title}, driver_name={self.driver_name})>"


class ledpanel(db.Model):
    __tablename__ = 'ledpanel'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    endpoint = db.Column(db.String(15), nullable=False)
    active_playlist = db.Column(db.String(30), nullable=False)
    brightness = db.Column(db.Integer, nullable=True)
    mode = db.Column(db.Integer, nullable=True, default=2)
    track = db.Column(db.Integer, nullable=True, default=1)

    def __repr__(self):
        return f"<ledpanel(id={self.id}, endpoint={self.endpoint}, active_playlist={self.active_playlist}, brightness={self.brightness})>"
