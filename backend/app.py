# ============================================================
# Mech Platform — WSGI Application Entry Point
# Used by gunicorn: gunicorn --worker-class eventlet app:application
#
# CRITICAL: eventlet.monkey_patch() MUST be called here,
# as the very first executable line, before ANY other import.
# If any other module is imported first, eventlet cannot patch
# the standard library correctly and gunicorn crashes with
# "Exited with status 1" or a RuntimeError at startup.
# ============================================================
import eventlet
eventlet.monkey_patch()  # ← MUST be before all other imports

import os
from app import create_app, socketio
from app.config import DevelopmentConfig, ProductionConfig

env    = os.environ.get("FLASK_ENV", "development")
config = ProductionConfig if env == "production" else DevelopmentConfig

application = create_app(config)

if __name__ == "__main__":
    port  = int(os.environ.get("PORT", 5000))
    debug = env != "production"
    socketio.run(
        application,
        host="0.0.0.0",
        port=port,
        debug=debug,
        use_reloader=debug,
        log_output=debug,
    )
