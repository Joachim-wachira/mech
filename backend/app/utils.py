"""
Mech Platform — Utility Functions
"""
import math
import random
import string
from datetime import datetime, timedelta
from functools import wraps
from flask import jsonify, current_app
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
from app.models import User


def haversine_km(lat1, lng1, lat2, lng2):
    """Return great-circle distance in kilometres between two WGS-84 points."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def generate_sms_code(length=6):
    """Return a random numeric SMS OTP."""
    return "".join(random.choices(string.digits, k=length))


def format_kes(amount):
    """Return a KES-formatted currency string, e.g. 'KES 2,450'."""
    return f"KES {amount:,.0f}"


def paginate_query(query, page, per_page=20):
    """Return a paginated response dict."""
    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": math.ceil(total / per_page) if per_page else 1,
    }


def role_required(*roles):
    """Decorator: allow access only to users with the specified role(s)."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            user_id = get_jwt_identity()
            user = User.query.get(user_id)
            if not user:
                return jsonify({"error": "User not found"}), 404
            if user.role not in roles:
                return jsonify({"error": "Access denied"}), 403
            if not user.is_active or user.is_suspended:
                return jsonify({"error": "Account suspended or inactive"}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def current_user():
    """Return the currently authenticated User model, or None."""
    try:
        verify_jwt_in_request()
        user_id = get_jwt_identity()
        return User.query.get(user_id)
    except Exception:
        return None


def success_response(data=None, message="", status=200):
    body = {"success": True}
    if message:
        body["message"] = message
    if data is not None:
        body.update(data)
    return jsonify(body), status


def error_response(message, status=400):
    return jsonify({"success": False, "error": message}), status


def nearby_providers(role, lat, lng, radius_km=None):
    """Return User objects of the given role within radius_km, sorted by distance."""
    from app import db
    if radius_km is None:
        radius_km = current_app.config.get("NEARBY_RADIUS_KM", 25)

    users = (
        User.query
        .filter_by(role=role, is_active=True, is_available=True)
        .filter(User.location_lat.isnot(None), User.location_lng.isnot(None))
        .all()
    )

    results = []
    for u in users:
        dist = haversine_km(lat, lng, u.location_lat, u.location_lng)
        if dist <= radius_km:
            d = u.to_dict()
            d["distance"] = round(dist, 2)
            results.append(d)

    results.sort(key=lambda x: x["distance"])
    return results
