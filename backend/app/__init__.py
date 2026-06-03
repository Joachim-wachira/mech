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
    engine_opts = app.config.get("SQLALCHEMY_ENGINE_OPTIONS", {}).copy()
    if "connect_args" not in engine_opts:
        engine_opts["connect_args"] = {}
    engine_opts["connect_args"].setdefault("connect_timeout", 10)
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = engine_opts

    # ── Extensions ────────────────────────────────────────────
    db.init_app(app)

    # ✅ FIXED: CORS now allows both the frontend Render URL AND any origin
    # The previous code had a fatal bug: when config_object was passed,
    # it called `return app` early — before registering ANY blueprints,
    # DB init, or SocketIO. This meant production got a broken app with
    # no routes at all. That early-return is now removed.
    CORS(app,
         resources={r"/api/*": {"origins": "*"}},
         supports_credentials=True)

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

    # ── Admin seed route (create first admin user) ────────────
    # POST /api/setup-admin  { "email": "...", "password": "...", "phone": "...", "full_name": "..." }
    # Protected by SETUP_SECRET env var — delete this route after first use!
    @app.route("/api/setup-admin", methods=["POST"])
    def setup_admin():
        from flask import request, jsonify
        from app.models import User
        from werkzeug.security import generate_password_hash

        setup_secret = os.environ.get("SETUP_SECRET", "")
        if not setup_secret:
            return jsonify({"error": "SETUP_SECRET env var not set"}), 403

        provided = request.headers.get("X-Setup-Secret", "")
        if provided != setup_secret:
            return jsonify({"error": "Forbidden"}), 403

        data = request.get_json() or {}
        required = ["email", "password", "phone", "full_name"]
        if not all(k in data for k in required):
            return jsonify({"error": f"Required fields: {required}"}), 400

        if User.query.filter_by(role="admin").first():
            return jsonify({"error": "Admin already exists. Use /api/auth/login"}), 409

        admin = User(
            full_name=data["full_name"],
            email=data["email"].strip().lower(),
            phone=data["phone"].strip(),
            role="admin",
            is_verified=True,
            is_active=True,
            phone_verified=True,
        )
        admin.password_hash = generate_password_hash(data["password"])
        db.session.add(admin)
        db.session.commit()
        return jsonify({"success": True, "message": "Admin created. Now login at /api/auth/login"}), 201

    return app
