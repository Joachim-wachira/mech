# ============================================================
# Mech Platform — WSGI Application Entry Point
# Used by gunicorn: gunicorn --worker-class gevent --workers 1
#                   --bind 0.0.0.0:$PORT --timeout 120
#                   --keep-alive 5 wsgi:application
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

# Startup sanity check — printed to Render logs before any request arrives.
# If DATABASE_URL is missing this will be the first thing you see.
_db_url = os.environ.get("DATABASE_URL", "")
if _db_url:
    import re as _re
    _safe = _re.sub(r":[^@]+@", ":***@", _db_url)
    print(f"[wsgi] FLASK_ENV={env}  DATABASE_URL={_safe}", flush=True)
else:
    print("[wsgi] WARNING: DATABASE_URL env var is NOT SET — DB will be unavailable", flush=True)

# FIX: Disable pool_pre_ping at engine-creation time on Render.
# SQLAlchemy's pool_pre_ping issues a "SELECT 1" when a connection is first
# checked out of the pool — not at startup. However, combined with gevent
# monkey-patching, the psycopg2 DNS resolution for the Render-internal
# Postgres hostname (dpg-xxxxx) can fire during worker boot before the
# Render network is fully ready, causing:
#   OperationalError: could not translate host name "dpg-..." to address
#
# pool_pre_ping is still set in config.py so it takes effect for all
# connections after boot. This override only affects the engine object
# created during worker initialisation; it is a no-op for connection
# health checks at request time (which is when pre_ping actually runs).
#
# The correct approach for Render free-tier is:
#   1. No DB touch at all during worker init (enforced here + in __init__.py)
#   2. Lazy db.create_all() on first real API request (in __init__.py)
#   3. pool_recycle keeps stale connections from breaking long-idle dynos

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
