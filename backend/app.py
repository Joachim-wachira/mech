# ============================================================
# Mech Platform — WSGI Application Entry Point
# Used by gunicorn: gunicorn --worker-class gevent app:application
#
# CRITICAL: gevent.monkey.patch_all() MUST be called here,
# as the very first executable line, before ANY other import.
# ============================================================
from gevent import monkey
monkey.patch_all()  # ← MUST be before all other imports

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
