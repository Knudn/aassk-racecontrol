
from flask import render_template, url_for, redirect
from app import app, db
from app.models import ConfigForm, Configuration, db

@app.route("/")
def index():
    services = Configuration.query.all()
    return render_template("index.html", services=services)

@app.route("/global_configuration")
def global_config():  

    form = ConfigForm()
    if form.validate_on_submit():
        if 'submit' in request.form:
            config = Configuration(
                session_name=form.session_name.data,
                project_dir=form.project_dir.data,
                db_location=form.db_location.data,
                event_dir=form.event_dir.data,
                wl_title=form.wl_title.data
            )
            db.session.add(config)
            db.session.commit()
            return redirect(url_for('admin'))
        else:
            print("test")

    # Retrieve the latest configuration from the database
    latest_config = Configuration.query.order_by(Configuration.id.desc()).first()
    if latest_config:
        form.session_name.data = latest_config.session_name
        form.project_dir.data = latest_config.project_dir
        # ... populate other fields
    return render_template('configure.html', form=form)