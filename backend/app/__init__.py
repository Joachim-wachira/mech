"""
Mech Platform — Flask Application Factory
"""
import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from flask_cors import CORS
from flask_jwt_extended import JWTManager

db       = SQLAlchemy()
socketio = SocketIO()
jwt      = JWTManager()


def create_app(config_object=None):
    app = Flask(__name__)

    # ── Load config ───────────────────────────────────────────
    if config_object:
        app.config.from_object(config_object)
        CORS(app,
             resources={r"/api/*":{"origins": [https://mech-frontend.onrender.com]}}
             supports_credentials=True)
        return app
    else:
        from app.config import DevelopmentConfig
        app.config.from_object(DevelopmentConfig)

    # ── Fix Render's postgres:// → postgresql:// at runtime ──
    db_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if db_uri.startswith("postgres://"):
        app.config["SQLALCHEMY_DATABASE_URI"] = db_uri.replace(
            "postgres://", "postgresql://", 1
        )

    # ── Add connection timeout so startup never hangs ─────────
    # Without this, db.create_all() blocks forever if postgres
    # is slow to accept connections (common on Render free tier).
    engine_opts = app.config.get("SQLALCHEMY_ENGINE_OPTIONS", {}).copy()
    if "connect_args" not in engine_opts:
        engine_opts["connect_args"] = {}
    engine_opts["connect_args"].setdefault("connect_timeout", 10)
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = engine_opts

    # ── Extensions ────────────────────────────────────────────
    db.init_app(app)
    CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)
    jwt.init_app(app)
    socketio.init_app(
        app,
        cors_allowed_origins="*",
        async_mode="gevent",
        logger=False,
        engineio_logger=False,
    )

    # ── Register blueprints ───────────────────────────────────
    from app.auth             import auth_bp
    from app.routes           import routes_bp
    from app.admin_routes     import admin_bp
    from app.payments         import payments_bp
    from app.emergency_routes import emergency_bp
    from app.ratings_routes   import ratings_bp

    app.register_blueprint(auth_bp,       url_prefix="/api/auth")
    app.register_blueprint(routes_bp,     url_prefix="/api")
    app.register_blueprint(admin_bp,      url_prefix="/api/admin")
    app.register_blueprint(payments_bp,   url_prefix="/api/payments")
    app.register_blueprint(emergency_bp,  url_prefix="/api/emergency")
    app.register_blueprint(ratings_bp,    url_prefix="/api/ratings")

    # ── WebSocket handlers (side-effect import) ───────────────
    from app import chat  # noqa: F401

    # ── Create DB tables on first request (not at startup) ────
    # IMPORTANT: do NOT call db.create_all() here directly.
    # Calling it in the factory blocks gunicorn worker boot when
    # the postgres connection is slow (Render free tier).
    # Instead we create tables lazily on the first HTTP request.
    _db_ready = {"done": False}

    @app.before_request
    def _init_db():
        if not _db_ready["done"]:
            _db_ready["done"] = True
            try:
                db.create_all()
            except Exception as e:
                app.logger.warning(f"db.create_all() skipped: {e}")

    # ── Health check (Render pings this to confirm startup) ───
    @app.route("/health")
    def health():
        return {"status": "ok", "app": "mech"}, 200

    return app
