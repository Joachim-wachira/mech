"""
Mech Platform — Emergency Contacts Routes
Blueprint: emergency_bp  →  registered at /api/emergency in __init__.py

Endpoints:
  GET  /api/emergency/contacts        — public, no auth required
  POST /api/emergency/log             — JWT required, logs a call to DB
  GET  /api/emergency/logs            — JWT required, user's own call history

Data source priority:
  1. frontend/data/emergency_contacts.xlsx  (editable by admin)
  2. FALLBACK_CONTACTS hardcoded list       (always works, even offline)
"""

import os
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity

try:
    import openpyxl
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False

emergency_bp = Blueprint("emergency", __name__)

# ── Excel file path ───────────────────────────────────────────────
# Adjust this relative path if your repo layout changes.
EXCEL_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),   # backend/app/
    "..", "..", "frontend", "data", "emergency_contacts.xlsx"
)

# ── Hardcoded fallback (Kirinyaga County) ─────────────────────────
FALLBACK_CONTACTS = [
    {"id": 1,  "name": "Kirinyaga County Ambulance & Fire", "location": "Kerugoya / County-wide",      "contact": "0711 234567",  "category": "Ambulance", "notes": "Main county emergency line for ambulance and fire", "available_24_7": True,  "icon": "🚑"},
    {"id": 2,  "name": "Kerugoya County Hospital",          "location": "Kerugoya",                    "contact": "020 3522252",  "category": "Medical",   "notes": "Call for ambulance or medical emergencies",         "available_24_7": True,  "icon": "🏥"},
    {"id": 3,  "name": "Police / Fire / Ambulance",         "location": "Kirinyaga County",            "contact": "999",          "category": "Police",    "notes": "National lines — also try 112",                     "available_24_7": True,  "icon": "🚔"},
    {"id": 4,  "name": "Baricho Police Station",            "location": "Baricho, Kirinyaga",          "contact": "060-21732",    "category": "Police",    "notes": "Local police station",                             "available_24_7": True,  "icon": "🚔"},
    {"id": 5,  "name": "Kianyaga Police Station",           "location": "Kianyaga, Kirinyaga",         "contact": "060-751002",   "category": "Police",    "notes": "Local police station",                             "available_24_7": True,  "icon": "🚔"},
    {"id": 6,  "name": "OCPD Office Kirinyaga",             "location": "Kirinyaga",                   "contact": "060-21266",    "category": "Police",    "notes": "County Police Director office",                     "available_24_7": True,  "icon": "🚔"},
    {"id": 7,  "name": "Sagana Police Station",             "location": "Sagana, Kirinyaga",           "contact": "060-46002",    "category": "Police",    "notes": "Local police station",                             "available_24_7": True,  "icon": "🚔"},
    {"id": 8,  "name": "Kenya Red Cross",                   "location": "Nationwide (incl. Kirinyaga)","contact": "1199",         "category": "Ambulance", "notes": "Free 24/7 ambulance — works in Kirinyaga",          "available_24_7": True,  "icon": "🏥"},
    {"id": 9,  "name": "National Fire Service",             "location": "Nationwide",                  "contact": "020-2222181",  "category": "Fire",      "notes": "National fire brigade emergency line",              "available_24_7": True,  "icon": "🔥"},
    {"id": 10, "name": "National Fire Service (Alt)",       "location": "Nationwide",                  "contact": "020-2344599",  "category": "Fire",      "notes": "Alternative national fire brigade line",            "available_24_7": True,  "icon": "🔥"},
]

_ICON_MAP = {"Ambulance": "🚑", "Medical": "🏥", "Police": "🚔", "Fire": "🔥"}


def _load_from_excel():
    """Try to load emergency contacts from the Excel sheet. Returns list or None."""
    if not OPENPYXL_AVAILABLE:
        return None
    path = os.path.abspath(EXCEL_PATH)
    if not os.path.exists(path):
        return None
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        contacts = []
        for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True)):
            num, name, location, contact, notes, category, available = (list(row) + [None] * 7)[:7]
            if not name:
                continue
            cat = str(category or "").strip()
            contacts.append({
                "id":            int(num) if num else i + 1,
                "name":          str(name).strip(),
                "location":      str(location or "").strip(),
                "contact":       str(contact or "").strip(),
                "notes":         str(notes or "").strip(),
                "category":      cat,
                "available_24_7": str(available or "").strip().lower() == "yes",
                "icon":          _ICON_MAP.get(cat, "🚨"),
            })
        wb.close()
        return contacts or None
    except Exception as exc:
        current_app.logger.warning(f"[emergency] Could not read Excel: {exc}")
        return None


# ── Routes ────────────────────────────────────────────────────────

@emergency_bp.route("/contacts", methods=["GET"])
def get_emergency_contacts():
    """
    Returns all emergency contacts (no auth required — emergencies are always accessible).
    Optional query param: ?category=Police|Medical|Fire|Ambulance
    """
    contacts = _load_from_excel() or FALLBACK_CONTACTS
    source   = "excel" if _load_from_excel() else "fallback"

    category = request.args.get("category", "").strip()
    if category:
        contacts = [c for c in contacts if c.get("category", "").lower() == category.lower()]

    return jsonify({"contacts": contacts, "source": source, "count": len(contacts)}), 200


@emergency_bp.route("/log", methods=["POST"])
@jwt_required()
def log_emergency_call():
    """
    Logs an emergency call to the database.
    Called automatically by chat.html when the user taps 📞 on an emergency contact.
    Body: { service_name, contact, timestamp? }
    """
    # Import here to avoid circular imports at module load time
    from app import db
    from app.models import EmergencyCallLog

    user_id = get_jwt_identity()
    data    = request.get_json(silent=True) or {}

    service_name = data.get("service_name", "").strip()
    contact      = data.get("contact", "").strip()
    timestamp    = data.get("timestamp")

    if not service_name or not contact:
        return jsonify({"error": "service_name and contact are required"}), 400

    try:
        called_at = (
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if timestamp else datetime.now(timezone.utc)
        )
        log = EmergencyCallLog(
            user_id      = user_id,
            service_name = service_name,
            contact      = contact,
            called_at    = called_at,
        )
        db.session.add(log)
        db.session.commit()
        return jsonify({"message": "Emergency call logged", "log_id": log.id}), 201
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error(f"[emergency log] {exc}")
        return jsonify({"error": "Could not save log"}), 500


@emergency_bp.route("/logs", methods=["GET"])
@jwt_required()
def get_emergency_logs():
    """Returns the authenticated user's emergency call history (latest 50)."""
    from app import db
    from app.models import EmergencyCallLog

    user_id = get_jwt_identity()
    try:
        logs = (
            EmergencyCallLog.query
            .filter_by(user_id=user_id)
            .order_by(EmergencyCallLog.called_at.desc())
            .limit(50)
            .all()
        )
        return jsonify({"logs": [l.to_dict() for l in logs]}), 200
    except Exception as exc:
        current_app.logger.error(f"[emergency logs] {exc}")
        return jsonify({"logs": []}), 200
