"""
Samuraizer – Flask application factory and boot sequence.
"""

import os

from flask import Flask, jsonify

import backend.config as cfg
from backend.database import init_db, close_db
from backend.routes import register_blueprints
from backend.services.backup import make_db_backup, start_backup_scheduler
from backend.services.feeds import start_rss_scheduler


def create_app() -> Flask:
    app = Flask(__name__)

    # ── CORS ───────────────────────────────────────────────────────────────
    @app.after_request
    def add_cors(resp):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return resp

    # Catch-all OPTIONS preflight (covers every route; individual route-level
    # OPTIONS handlers like the YT-channels ones still take precedence).
    @app.route("/<path:path>", methods=["OPTIONS"])
    @app.route("/", methods=["OPTIONS"], defaults={"path": ""})
    def preflight(path):
        return "", 204

    # ── Teardown ───────────────────────────────────────────────────────────
    @app.teardown_appcontext
    def teardown_db(_):
        close_db()

    # ── Blueprints ─────────────────────────────────────────────────────────
    register_blueprints(app)

    # ── Boot ───────────────────────────────────────────────────────────────
    init_db()

    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    # When running with the Flask reloader, only run backups/schedulers
    # in the reloader child to avoid duplicate work.
    if not debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        make_db_backup("startup")
        start_backup_scheduler(12)

    start_rss_scheduler()

    return app
