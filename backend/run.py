"""
Mech Platform — Development Runner
Usage: python run.py
"""
import os
from app import create_app, socketio
from app.config import DevelopmentConfig

os.environ.setdefault("FLASK_ENV", "development")

app = create_app(DevelopmentConfig)

if __name__ == "__main__":
    print("\n🚗  Mech Platform — Development Server")
    print("    API:       http://localhost:5000")
    print("    WebSocket: ws://localhost:5000")
    print("    Docs:      http://localhost:5000/health\n")

    socketio.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=True,
        use_reloader=True,
        log_output=True,
    )
