"""
Samuraizer – Cyber-Security Insight Engine
Run: python server.py

Thin launcher.  All logic lives under backend/.
"""

import os
from backend.app import create_app
import backend.config as cfg

app = create_app()

if __name__ == "__main__":
    _debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(host=cfg.APP_HOST, port=cfg.APP_PORT, debug=_debug, use_reloader=_debug)