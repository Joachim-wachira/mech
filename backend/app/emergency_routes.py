"""
Mech Platform — Emergency Contacts Routes
Blueprint: emergency_bp  →  registered at /api/emergency in __init__.py

The platform operates WORLDWIDE. Emergency contacts are stored in:
  frontend/data/emergency_contacts.xlsx

This file is edited by admins to add counties, cities, and countries.
The backend reads it on every request — no restart needed after edits.

Endpoints:
  GET  /api/emergency/contacts          — public, no auth required
  GET  /api/emergency/contacts?country= — filter by country
  GET  /api/emergency/contacts?region=  — filter by region/county
  GET  /api/emergency/contacts?category=— filter by service category
  POST /api/emergency/log               — JWT, log a call to DB
  GET  /api/emergency/logs              — JWT, user's own call history
  GET  /api/emergency/countries         — public, list of countries in Excel
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

# Path to the admin-editable Excel sheet
EXCEL_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),   # backend/app/
    "..", "..", "frontend", "data", "emergency_contacts.xlsx"
)

# ── Worldwide fallback contacts ────────────────────────────────────
# These are used if the Excel file is unavailable.
# Kirinyaga contacts are included as an example — the Excel file
# is intended to be expanded by admins to cover all regions worldwide.
FALLBACK_CONTACTS = [
    # Kenya — Kirinyaga (example region)
    {"id":1,  "country":"Kenya",         "region":"Kirinyaga County",  "name":"Kirinyaga County Ambulance & Fire", "location":"Kerugoya / County-wide",       "contact":"0711 234567",   "category":"Ambulance",              "available_24_7":True,  "notes":"Main county emergency line. More counties to be added.", "icon":"🚑"},
    {"id":2,  "country":"Kenya",         "region":"Kirinyaga County",  "name":"Kerugoya County Hospital",          "location":"Kerugoya",                    "contact":"020 3522252",   "category":"Medical",                "available_24_7":True,  "notes":"Call for ambulance or medical emergencies",              "icon":"🏥"},
    {"id":3,  "country":"Kenya",         "region":"Nationwide",        "name":"Police / Fire / Ambulance",         "location":"Nationwide",                  "contact":"999 / 112",     "category":"Police / Fire / Ambulance","available_24_7":True, "notes":"National lines — work across all Kenya",                 "icon":"🚔"},
    {"id":4,  "country":"Kenya",         "region":"Kirinyaga County",  "name":"Baricho Police Station",            "location":"Baricho",                     "contact":"060-21732",     "category":"Police",                 "available_24_7":True,  "notes":"Local police station",                                   "icon":"🚔"},
    {"id":5,  "country":"Kenya",         "region":"Kirinyaga County",  "name":"Kianyaga Police Station",           "location":"Kianyaga",                    "contact":"060-751002",    "category":"Police",                 "available_24_7":True,  "notes":"Local police station",                                   "icon":"🚔"},
    {"id":6,  "country":"Kenya",         "region":"Kirinyaga County",  "name":"OCPD Office Kirinyaga",             "location":"Kirinyaga",                   "contact":"060-21266",     "category":"Police",                 "available_24_7":True,  "notes":"County Police Director office",                          "icon":"🚔"},
    {"id":7,  "country":"Kenya",         "region":"Kirinyaga County",  "name":"Sagana Police Station",             "location":"Sagana",                      "contact":"060-46002",     "category":"Police",                 "available_24_7":True,  "notes":"Local police station",                                   "icon":"🚔"},
    {"id":8,  "country":"Kenya",         "region":"Nationwide",        "name":"Kenya Red Cross",                   "location":"Nationwide",                  "contact":"1199",          "category":"Ambulance",              "available_24_7":True,  "notes":"Free 24/7 ambulance service",                            "icon":"🏥"},
    {"id":9,  "country":"Kenya",         "region":"Nationwide",        "name":"National Fire Service",             "location":"Nationwide",                  "contact":"020-2222181",   "category":"Fire",                   "available_24_7":True,  "notes":"National fire brigade",                                  "icon":"🔥"},
    {"id":10, "country":"Kenya",         "region":"Nationwide",        "name":"National Fire Service (Alt)",       "location":"Nationwide",                  "contact":"020-2344599",   "category":"Fire",                   "available_24_7":True,  "notes":"Alternative national fire brigade line",                  "icon":"🔥"},
    # International universal lines
    {"id":11, "country":"International", "region":"Europe",            "name":"General Emergency (EU)",            "location":"All EU countries",            "contact":"112",           "category":"Police / Fire / Ambulance","available_24_7":True, "notes":"Standard EU emergency number — works in all EU member states", "icon":"🚨"},
    {"id":12, "country":"International", "region":"North America",     "name":"General Emergency (US / Canada)",   "location":"United States & Canada",      "contact":"911",           "category":"Police / Fire / Ambulance","available_24_7":True, "notes":"Standard North American emergency number",               "icon":"🚨"},
    {"id":13, "country":"International", "region":"United Kingdom",    "name":"General Emergency (UK)",            "location":"United Kingdom",              "contact":"999",           "category":"Police / Fire / Ambulance","available_24_7":True, "notes":"UK emergency number",                                    "icon":"🚨"},
    {"id":14, "country":"International", "region":"Australia",         "name":"General Emergency (Australia)",     "location":"Australia",                   "contact":"000",           "category":"Police / Fire / Ambulance","available_24_7":True, "notes":"Australian emergency number",                            "icon":"🚨"},
    {"id":15, "country":"International", "region":"India",             "name":"General Emergency (India)",         "location":"India",                       "contact":"112",           "category":"Police / Fire / Ambulance","available_24_7":True, "notes":"India unified emergency number",                         "icon":"🚨"},
    {"id":16, "country":"International", "region":"South Africa",      "name":"General Emergency (South Africa)",  "location":"South Africa",                "contact":"10111",         "category":"Police",                 "available_24_7":True,  "notes":"SA Police. Ambulance: 10177",                            "icon":"🚔"},
    {"id":17, "country":"International", "region":"Nigeria",           "name":"General Emergency (Nigeria)",       "location":"Nigeria",                     "contact":"112",           "category":"Police / Fire / Ambulance","available_24_7":True, "notes":"Nigeria unified emergency number",                        "icon":"🚨"},
    {"id":18, "country":"International", "region":"Worldwide",         "name":"International SOS",                 "location":"Worldwide",                   "contact":"+1-215-942-8226","category":"Medical / Rescue",       "available_24_7":True,  "notes":"24/7 worldwide medical and security assistance",          "icon":"🏥"},
]

_ICON_MAP = {
    "Ambulance": "🚑", "Medical": "🏥",
    "Police": "🚔",    "Fire": "🔥",
    "Police / Fire / Ambulance": "🚨",
    "Medical / Rescue": "🏥",
    "Ambulance / Fire": "🚑",
}


def _load_from_excel():
    """
    Load emergency contacts from the admin-editable Excel sheet.
    Columns (row 1 = header, data from row 2):
      #, Country, Region / County, Service Name, Location,
      Emergency Contact, Category, Available 24/7, Notes
    Returns list of dicts or None if unavailable.
    """
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
            # Pad to 9 cols in case trailing empties are missing
            cells = (list(row) + [None] * 9)[:9]
            num, country, region, name, location, contact, category, available, notes = cells

            name_str = str(name).strip()
            name_upper = name_str.upper()
            # Skip blank rows, admin notes, and any instructional placeholder rows
            if (not name_str or
                name_upper.startswith("ADMIN") or
                name_upper.startswith("ADD MORE") or
                name_upper.startswith("ADD ") or
                "COUNTIES" in name_upper or
                "COUNTRIES BELOW" in name_upper or
                "EDIT THIS" in name_upper or
                name_upper.startswith("NOTE:") or
                not contact):
                continue  # skip blank, instructional, or incomplete rows

            cat = str(category or "").strip()
            contacts.append({
                "id":            int(num) if num else i + 1,
                "country":       str(country  or "").strip(),
                "region":        str(region   or "").strip(),
                "name":          str(name     or "").strip(),
                "location":      str(location or "").strip(),
                "contact":       str(contact  or "").strip(),
                "category":      cat,
                "available_24_7": str(available or "").strip().lower() == "yes",
                "notes":         str(notes    or "").strip(),
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
    Returns emergency contacts — no authentication required.
    Emergency information must always be accessible.

    Query params (all optional, combinable):
      ?country=Kenya          — filter by country
      ?region=Kirinyaga       — filter by region/county (partial match)
      ?category=Police        — filter by service category
    """
    contacts = _load_from_excel() or FALLBACK_CONTACTS
    source   = "excel" if _load_from_excel() else "fallback"

    # Apply filters
    country  = request.args.get("country",  "").strip().lower()
    region   = request.args.get("region",   "").strip().lower()
    category = request.args.get("category", "").strip().lower()

    if country:
        contacts = [c for c in contacts if country in c.get("country","").lower()]
    if region:
        contacts = [c for c in contacts if region in c.get("region","").lower()]
    if category:
        contacts = [c for c in contacts if category in c.get("category","").lower()]

    return jsonify({
        "contacts": contacts,
        "count":    len(contacts),
        "source":   source,
        "note":     "This list covers multiple countries and regions. Edit frontend/data/emergency_contacts.xlsx to add more.",
    }), 200


@emergency_bp.route("/countries", methods=["GET"])
def list_countries():
    """
    Returns a sorted list of countries present in the contacts file.
    Useful for populating a country filter dropdown in the frontend.
    No authentication required.
    """
    contacts = _load_from_excel() or FALLBACK_CONTACTS
    countries = sorted(set(c.get("country","") for c in contacts if c.get("country") and c.get("country") != "ADMIN NOTE"))
    return jsonify({"countries": countries, "count": len(countries)}), 200


@emergency_bp.route("/log", methods=["POST"])
@jwt_required()
def log_emergency_call():
    """
    Log an emergency call to the database.
    Called automatically by chat.html when the user taps 📞 on a contact.
    Body: { service_name, contact, country?, region?, timestamp? }
    """
    from app import db
    from app.models import EmergencyCallLog

    user_id = get_jwt_identity()
    data    = request.get_json(silent=True) or {}

    service_name = data.get("service_name", "").strip()
    contact      = data.get("contact",      "").strip()
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
