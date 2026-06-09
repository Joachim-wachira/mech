"""
Mech Platform — Flask Application Factory
"""
import os
from flask import Flask, jsonify, request as flask_request
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

    # ── Fix Render's postgres:// → postgresql:// ──────────────
    db_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if db_uri.startswith("postgres://"):
        app.config["SQLALCHEMY_DATABASE_URI"] = db_uri.replace(
            "postgres://", "postgresql://", 1
        )

    # ── Extensions ────────────────────────────────────────────
    db.init_app(app)

    # ── Startup diagnostic — log what DB URI is actually in use ──
    # This appears in Render logs immediately on boot so you can confirm
    # DATABASE_URL is set correctly without needing to connect to the DB.
    _uri = app.config.get("SQLALCHEMY_DATABASE_URI", "") or ""
    if _uri:
        # Mask password in the log: postgresql://user:PASS@host/db → ...@host/db
        import re as _re
        _safe_uri = _re.sub(r":[^@]+@", ":***@", _uri)
        app.logger.info(f"[mech] DB URI → {_safe_uri}")
    else:
        app.logger.error("[mech] DATABASE_URL is NOT SET — all DB requests will fail with 503")

    # FIX 1: Do NOT combine supports_credentials=True with origins="*".
    # Browsers hard-block credentialed requests to wildcard origins (CORS spec).
    # JWT tokens travel in the Authorization header — credentials mode is not needed.
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    jwt.init_app(app)
    socketio.init_app(
        app,
        cors_allowed_origins="*",
        async_mode="gevent",
        logger=False,
        engineio_logger=False,
    )

    # ── Register blueprints ───────────────────────────────────
    from app.auth                import auth_bp
    from app.routes              import routes_bp
    from app.admin_routes        import admin_bp
    from app.payments            import payments_bp
    from app.emergency_routes    import emergency_bp
    from app.ratings_routes      import ratings_bp
    from app.subscription_routes import subscription_bp

    app.register_blueprint(auth_bp,          url_prefix="/api/auth")
    app.register_blueprint(routes_bp,        url_prefix="/api")
    app.register_blueprint(admin_bp,         url_prefix="/api/admin")
    app.register_blueprint(payments_bp,      url_prefix="/api/payments")
    app.register_blueprint(emergency_bp,     url_prefix="/api/emergency")
    app.register_blueprint(ratings_bp,       url_prefix="/api/ratings")
    app.register_blueprint(subscription_bp,  url_prefix="/api/subscriptions")

    # ── WebSocket handlers (side-effect import) ───────────────
    from app import chat  # noqa: F401

    # ── DB table creation — lazy, on first suitable request ───
    #
    # WHY NOT at startup:
    #   Render's internal PostgreSQL hostname (dpg-xxxxx) is only DNS-resolvable
    #   from within Render's runtime network AFTER the dyno is fully booted.
    #   Any DB touch during gunicorn worker init raises:
    #     psycopg2.OperationalError: could not translate host name "dpg-..." to address
    #
    # WHY before_request needs careful guards:
    #   Render probes several paths during deploy:
    #     HEAD /          ← Go-http-client probe, fires before DB DNS is ready
    #     GET  /health    ← Render health check (must return 200, no DB needed)
    #   Browser CORS preflights:
    #     OPTIONS /api/*  ← If we return 503 here, Flask-CORS never adds
    #                       Access-Control headers → browser reports CORS error
    #
    # THE FIX:
    #   Skip _ensure_tables for OPTIONS, HEAD, and /health.
    #   For every other request, attempt create_all() once and cache success.
    #   On failure, return 503 with JSON so the frontend shows a real message.
    #
    _tables_created = {"ok": False}

    # Paths and methods that must NEVER trigger a DB connection attempt
    _SKIP_DB_PATHS   = {"/health", "/"}
    _SKIP_DB_METHODS = {"OPTIONS", "HEAD"}

    @app.before_request
    def _ensure_tables():
        import time
        # Let preflight, probe, and health requests through untouched
        if flask_request.method in _SKIP_DB_METHODS:
            return
        if flask_request.path in _SKIP_DB_PATHS:
            return

        if _tables_created["ok"]:
            return  # already done — fast path

        # Guard: if DATABASE_URL was never set, fail fast with a clear error
        # instead of wasting 10 seconds on retries that will never succeed.
        _uri = app.config.get("SQLALCHEMY_DATABASE_URI", "") or ""
        if not _uri:
            app.logger.error("_ensure_tables: DATABASE_URL is empty — check Render env vars")
            return jsonify({
                "success": False,
                "error": "Server configuration error: database URL not set."
            }), 503

        # Retry up to 5 times with 2-second delays.
        # On Render free tier the Postgres DNS resolves within a few seconds of
        # the first real request, so one or two retries is usually enough.
        last_exc = None
        for attempt in range(1, 6):
            try:
                db.create_all()
                _tables_created["ok"] = True
                app.logger.info(f"db.create_all() — tables ready (attempt {attempt})")
                return  # success — let the request continue
            except Exception as exc:
                last_exc = exc
                app.logger.warning(f"db.create_all() attempt {attempt}/5 failed: {exc}")
                if attempt < 5:
                    time.sleep(2)

        # All retries exhausted — tell the user to retry
        app.logger.error(f"db.create_all() gave up after 5 attempts: {last_exc}")
        return jsonify({
            "success": False,
            "error": "Database not ready — please retry in a moment."
        }), 503

    # ── Global error handlers — always return JSON ────────────
    @app.errorhandler(500)
    def internal_error(e):
        app.logger.error(f"Unhandled 500: {e}")
        return jsonify({"success": False, "error": "Internal server error — check Render logs"}), 500

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"success": False, "error": "Endpoint not found"}), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify({"success": False, "error": "Method not allowed"}), 405

    # ── Health check — NEVER touches the DB ──────────────────
    # Render polls this during deploy; must return 200 immediately.
    @app.route("/health")
    def health():
        return jsonify({"status": "ok", "app": "mech"}), 200

    # ── Root probe — return 200 so HEAD / doesn't stall deploy ─
    # Render's Go-http-client sends HEAD / during the boot window
    # before Postgres DNS is resolvable. Returning 200 here prevents
    # that probe from triggering _ensure_tables and crashing.
    @app.route("/")
    def root():
        return jsonify({"status": "ok", "app": "mech"}), 200

    # ── One-time admin setup ──────────────────────────────────
    # POST /api/setup-admin   Header: X-Setup-Secret: <SETUP_SECRET env var>
    # Body: { full_name, email, phone, password }
    # Remove SETUP_SECRET from Render env after first use.
    @app.route("/api/setup-admin", methods=["POST"])
    def setup_admin():
        from flask import request
        from app.models import User
        from werkzeug.security import generate_password_hash

        setup_secret = os.environ.get("SETUP_SECRET", "")
        if not setup_secret:
            return jsonify({"error": "SETUP_SECRET env var not set"}), 403
        if request.headers.get("X-Setup-Secret", "") != setup_secret:
            return jsonify({"error": "Forbidden"}), 403

        data = request.get_json() or {}
        for field in ["email", "password", "phone", "full_name"]:
            if not data.get(field):
                return jsonify({"error": f"Missing required field: {field}"}), 400

        if User.query.filter_by(role="admin").first():
            return jsonify({"error": "Admin already exists — use /api/auth/login"}), 409

        admin = User(
            full_name      = data["full_name"],
            email          = data["email"].strip().lower(),
            phone          = data["phone"].strip(),
            role           = "admin",
            is_verified    = True,
            is_active      = True,
            phone_verified = True,
        )
        admin.password_hash = generate_password_hash(data["password"])
        db.session.add(admin)
        db.session.commit()
        return jsonify({"success": True, "message": "Admin created. Login at /api/auth/login"}), 201

    return app
