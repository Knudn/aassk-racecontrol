# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AASSK Race Control is a Flask-based web application for managing snowmobile/watercross racing events. It handles event scheduling, driver tracking, real-time race timing, display boards, LED panels, and hardware integration via MQTT. The system runs as a central hub with several microservice scripts managed via `screen` sessions.

## Running the Application

```bash
# Install dependencies
pip install -r requirements.txt

# Run the app (default host 0.0.0.0, port 7777)
python run.py

# Run with a specific host IP
python run.py --host 192.168.1.100
```

The app auto-initializes the SQLite database (`site.db`) and starts configured microservices on first run. No build step needed. No formal test suite exists.

## Architecture

### Flask App (`app/`)

- **`__init__.py`** — App factory (`create_app()`). Initializes Flask, SQLAlchemy, SocketIO, MQTT client, registers all blueprints.
- **`models.py`** — SQLAlchemy models. Several singleton models use `id=1` (GlobalConfig, ActiveDrivers, StartLogic, SpeakerPageSettings). CrossConfig, ledpanel, MicroServices, archive_server are multi-row.
- **`config/websocket_config.py`** — SocketIO event handlers and room definitions (clock_mgnt, infoscreen, admin, prestage_lights, etc.).
- **`lib/`** — Shared logic:
  - `db_operation.py` — Database queries and mutations (active events, startlists, race records)
  - `db_func.py` — Lower-level DB utility functions
  - `utils.py` — Helpers (driver sorting, time conversion, environment detection, screen session management)

### Blueprints (URL routing)

| Blueprint | Prefix | Purpose |
|-----------|--------|---------|
| `index_bp` | `/` | Redirects to admin |
| `admin_bp` | `/admin` | Main admin interface |
| `api_bp` | `/api` | REST API (sub-routes below) |
| `vmix_bp` | `/vmix` | vMix broadcast integration displays |
| `board_bp` | `/board` | Public display boards (startlists, scoreboards, ladders) |
| `cross_bp` | `/cross` | Watercross/snowcross-specific features |
| `infoscreen_bp` | `/infoscreen` | InfoScreen asset management |

### API Routes (`app/views/api_routes/`)

API endpoints are modular and registered onto `api_bp`:
- `event_routes.py` — Event CRUD, heat management
- `driver_routes.py` — Driver operations
- `timedata_routes.py` — Timing data and race records
- `archive_routes.py` — Archive server integration
- `system_routes.py` — System monitoring (uptime, etc.)

### Microservices (`scripts/`)

Standalone Python scripts run in `screen` sessions, managed via the MicroServices DB table and `manage_process_screen()` in `utils.py`:
- `mqtt_middleware.py` — MQTT start light logic and race state management
- `msport_display_proxy.py` — MSport timing system proxy
- `intermediate_list.py` / `intermediate_list_mylaps.py` — Real-time intermediate timing listeners
- `clock_server_vola.py` / `cross_clock_server.py` — Timing clock servers

### Configuration

- **`config.py`** (root) — App-wide defaults: port (7777), paths, default DB seed data for GlobalConfig, LED panels, microservices, infoscreen assets. `{host}` and `{ip}` are placeholder tokens replaced at runtime.
- **`run.py`** — Entry point. Parses `--host` arg, configures logging, initializes DB tables with defaults from `config.py`, starts microservices, launches SocketIO server.

### Database

SQLite (`site.db` in project root). Tables auto-created on startup. Key pattern: many config tables are singletons (query by `id=1`). Race data stored in `Session_Race_Records` with JSON blobs. The `ActiveEvents` table tracks enabled events with sort order and mode.

### Real-Time Communication

Flask-SocketIO handles WebSocket connections. Clients join named rooms for targeted updates. The admin interface, display boards, and hardware integrations all use socket events for live data.

## Key Conventions

- Python 3.11, Flask 3.1, SQLAlchemy 2.0
- Templates use Jinja2 in `app/templates/` organized by blueprint name
- Static assets (JS, CSS) in `app/static/`
- `paho-mqtt` is used but not listed in `requirements.txt`
- Logging goes to `logs/app.log` (rotating, 10MB max, 5 backups)
- CORS is fully open (`*`) on both Flask and SocketIO
