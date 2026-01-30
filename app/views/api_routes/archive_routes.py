# app/api/archive_routes.py
from flask import request, current_app
from app.lib.utils import export_events, GetEnv
from app.lib.db_operation import get_active_startlist_w_timedate
from app.models import archive_server, EventKvaliRate, ActiveEvents
from app import db
import requests
import json


def register_archive_routes(api_bp):
    """Register all archive-related routes with the API blueprint"""

    @api_bp.route("/api/check_remote_heartbeat/", methods=["GET"])
    def check_remote_heartbeat():
        microservices = archive_server.query.first()

        url = f"http://{microservices.hostname}/heartbeat"

        try:
            response = requests.get(url)
            if response.status_code == 200:
                return {"status": "OK"}
            else:
                return {"status": "ERROR"}, 500
        except Exception as e:
            current_app.logger.error(f"Error checking heartbeat: {str(e)}")
            return {"status": "ERROR", "message": str(e)}, 500

    @api_bp.route("/api/upate_remote_data", methods=["GET"])
    def upate_remote_data():
        g_config = GetEnv()

        update_type = request.args.get("type", type=str)

        archive_server_data = archive_server.query.first()

        if not g_config["msport_tm"]:
            race_type = "MyLaps Cross"
        else:
            race_type = "Msport"

        if not archive_server_data:
            return {"error": "Archive server data not found"}, 404

        password = archive_server_data.auth_token
        hostname = archive_server_data.hostname

        if update_type == "single":
            from app.models import Session_Race_Records

            send_data = get_active_startlist_w_timedate()
            single_event = True
            result = None
            event_data = None

            if not g_config["msport_tm"]:
                for k, a in enumerate(send_data):
                    if k == 0:
                        title_1 = a["race_config"]["TITLE_1"]
                        title_2 = a["race_config"]["TITLE_2"]
                        heat = a["race_config"]["HEAT"]
                        session_data = Session_Race_Records.query.filter(
                            Session_Race_Records.title_1 == title_1,
                            Session_Race_Records.title_2 == title_2,
                            Session_Race_Records.heat == heat,
                        ).all()
                    else:
                        for b in session_data:
                            if a["drivers"][0]["id"] == b.cid:
                                send_data[k]["drivers"][0]["time_info"]["POINTS"] = (
                                    b.points
                                )

        elif update_type == "full_sync":
            from app.models import Session_Race_Records

            title_1_filter = Session_Race_Records.query.first().title_1

            event_data = []

            single_event = False
            data = EventKvaliRate.query.all()
            events = (
                ActiveEvents.query.filter(ActiveEvents.enabled == 1)
                .order_by(ActiveEvents.sort_order)
                .all()
            )

            for k, a in enumerate(events):
                event_data.append(
                    {
                        "order": k,
                        "event_name": a.event_name.replace(title_1_filter, ""),
                        "run": a.run,
                        "mode": a.mode,
                    }
                )

            result = [event.to_dict() for event in data]
            send_data = export_events()
            revered_data = []
            if not g_config["msport_tm"]:
                points_data = ""
                for tk, a in enumerate(send_data):
                    for k, t in enumerate(a):
                        k += 1
                        if k == 1:
                            title_1 = t["race_config"]["TITLE_1"]
                            title_2 = t["race_config"]["TITLE_2"]
                            heat = t["race_config"]["HEAT"]
                            points_data = Session_Race_Records.query.filter(
                                Session_Race_Records.heat == heat,
                                Session_Race_Records.title_1 == title_1,
                                Session_Race_Records.title_2 == title_2,
                            ).all()
                        else:
                            if len(t["drivers"]) > 0:
                                for a in points_data:
                                    if (
                                        a.cid
                                        == send_data[tk][k - 1]["drivers"][0]["id"]
                                    ):
                                        send_data[tk][k - 1]["drivers"][0]["time_info"][
                                            "POINTS"
                                        ] = a.points

                                        # print(a.first_name, a.last_name, heat, a.points, a.laps)
                                print(title_1, title_2, heat)
                                print(send_data[tk][k - 1]["drivers"][0]["first_name"])
                                print(
                                    send_data[tk][k - 1]["drivers"][0]["time_info"][
                                        "FINISHTIME"
                                    ]
                                )

        else:
            return {"error": "Invalid update type"}, 400

        data = {
            "token": password,
            "data": send_data,
            "single_event": single_event,
            "race_type": race_type,
            "kvali_ranking": json.dumps(result) if result else None,
            "event_data": json.dumps(event_data) if event_data else None,
        }

        try:
            response = requests.post(f"http://{hostname}/api/realtime_data", json=data)
            if response.status_code == 200:
                return get_active_startlist_w_timedate()
            else:
                return {
                    "error": f"Remote server error: {response.status_code}"
                }, response.status_code
        except Exception as e:
            current_app.logger.error(f"Error updating remote data: {str(e)}")
            return {"error": f"Failed to update remote data: {str(e)}"}, 500

    @api_bp.route("/api/export/get_new_drivers", methods=["GET"])
    def get_new_drivers():
        archive_params = archive_server.query.first()

        try:
            current_drivers_response = requests.get(
                f"http://{archive_params.hostname}/get_drivers"
            )
            current_drivers = json.loads(current_drivers_response.text)
            current_events = export_events()

            events_names = []
            new_drivers = []

            for event in current_events:
                for run in event:
                    for heat in run:
                        if heat == "drivers":
                            try:
                                name = {
                                    "first_name": run[heat][0]["first_name"],
                                    "last_name": run[heat][0]["last_name"],
                                }
                                if name not in events_names:
                                    events_names.append(name)
                            except:
                                current_app.logger.warning("Could not add driver")

            for a in events_names:
                full_name = a["first_name"] + " " + a["last_name"]
                if full_name not in current_drivers:
                    new_drivers.append({"name": a, "new": True})
                else:
                    new_drivers.append({"name": a, "new": False})

            return {"new_driver": new_drivers, "data": current_events}
        except Exception as e:
            current_app.logger.error(f"Error getting new drivers: {str(e)}")
            return {"error": f"Failed to get new drivers: {str(e)}"}, 500

    @api_bp.route("/api/export/archive_race", methods=["POST"])
    def archive_race():
        archive_params = archive_server.query.first()
        race_data = request.json
        updated_data = json.dumps(race_data)

        headers = {"Content-Type": "application/json"}

        if archive_params.use_use_token:
            headers["token"] = str(archive_params.auth_token)

        url = f"http://{archive_params.hostname}/upload-data/"

        try:
            response = requests.post(url, headers=headers, data=updated_data)
            return response.json(), response.status_code
        except Exception as e:
            current_app.logger.error(f"Error archiving race: {str(e)}")
            return {"error": f"Failed to archive race: {str(e)}"}, 500

    @api_bp.route("/api/get_cup_results", methods=["GET"])
    def get_cup_results():
        url = f"https://resultatliste.aseralssk.no/cup?output=json"

        try:
            response = requests.get(url)
            if response.status_code == 200:
                return response.json()
            else:
                return {
                    "error": f"Failed to get cup results: {response.status_code}"
                }, response.status_code
        except Exception as e:
            current_app.logger.error(f"Error getting cup results: {str(e)}")
            return {"error": f"Failed to get cup results: {str(e)}"}, 500
