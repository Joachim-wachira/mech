"""
Mech Platform — Flask Application Factory
"""
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

    # ── Extensions ────────────────────────────────────────────
    db.init_app(app)
    CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)
    jwt.init_app(app)
    socketio.init_app(
        app,
        cors_allowed_origins="*",
        async_mode="eventlet",
        logger=False,
        engineio_logger=False,
    )

    # ── Register blueprints ───────────────────────────────────
    from app.auth            import auth_bp
    from app.routes          import routes_bp
    from app.admin_routes    import admin_bp
    from app.payments        import payments_bp
    from app.emergency_routes import emergency_bp   # ← was missing
    from app.ratings_routes  import ratings_bp      # ← was missing

    app.register_blueprint(auth_bp,       url_prefix="/api/auth")
    app.register_blueprint(routes_bp,     url_prefix="/api")
    app.register_blueprint(admin_bp,      url_prefix="/api/admin")
    app.register_blueprint(payments_bp,   url_prefix="/api/payments")
    app.register_blueprint(emergency_bp,  url_prefix="/api/emergency")   # ← registered
    app.register_blueprint(ratings_bp,    url_prefix="/api/ratings")     # ← registered

    # ── WebSocket handlers (side-effect import) ───────────────
    from app import chat  # noqa: F401

    # ── Create DB tables ──────────────────────────────────────
    with app.app_context():
        db.create_all()

    # ── Health check ──────────────────────────────────────────
    @app.route("/health")
    def health():
        return {"status": "ok", "app": "mech"}, 200

    return app
