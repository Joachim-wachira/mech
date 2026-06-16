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
    """Return the currently authenticated User model, or None.

    JWT identity is stored as a string (create_access_token(identity=str(user.id))).
    User.id is an Integer primary key — explicitly cast to int here so
    User.query.get() reliably matches, regardless of dialect/driver
    type-coercion behaviour. Without this, every @jwt_required() route
    that calls current_user() (including ALL /api/admin/* endpoints)
    could silently return None for a valid, logged-in admin.
    """
    try:
        verify_jwt_in_request()
        user_id = get_jwt_identity()
        return User.query.get(int(user_id))
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


def notify_via_chat(user_id, message, notification_type="admin"):
    """
    Creates an in-app Notification AND delivers the same message as a
    chat message from the "Mech Admin" system account, so it appears
    in the recipient's chat list with sender "Mech Admin". The
    conversation is read-only for the recipient (server-side guard in
    routes.py send_message_rest blocks replies to system accounts).

    Used by:
      - admin_routes.send_notification (manual admin → user/role/broadcast)
      - subscription_routes._notify (subscription reminders, lock/grace/etc.)

    Returns the created Message (caller may still need to db.session.commit()).
    """
    from app import db, socketio
    from app.models import Notification, Conversation, ConversationParticipant, Message

    n = Notification(user_id=user_id, message=message, notification_type=notification_type)
    db.session.add(n)

    bot = User.get_or_create_mech_admin()
    db.session.flush()

    my_convs    = {p.conversation_id for p in ConversationParticipant.query.filter_by(user_id=bot.id).all()}
    their_convs = {p.conversation_id for p in ConversationParticipant.query.filter_by(user_id=user_id).all()}
    shared = my_convs & their_convs
    if shared:
        conv_id = sorted(shared)[0]
    else:
        conv = Conversation()
        db.session.add(conv)
        db.session.flush()
        db.session.add(ConversationParticipant(conversation_id=conv.id, user_id=bot.id))
        db.session.add(ConversationParticipant(conversation_id=conv.id, user_id=user_id))
        conv_id = conv.id

    chat_msg = Message(
        conversation_id = conv_id,
        sender_id       = bot.id,
        content         = message,
        message_type    = "text",
    )
    db.session.add(chat_msg)
    db.session.flush()

    Conversation.query.get(conv_id).updated_at = datetime.utcnow()

    try:
        socketio.emit("notification", {"message": message}, room=f"user_{user_id}")
        socketio.emit("new_message", {
            "id":              chat_msg.id,
            "conversation_id": conv_id,
            "sender_id":       bot.id,
            "sender_name":     "Mech Admin",
            "message":         message,
            "content":         message,
            "message_type":    "text",
            "created_at":      chat_msg.created_at.isoformat(),
        }, room=f"user_{user_id}")
    except Exception:
        pass  # socket emit is best-effort; the message is already persisted

    return chat_msg


def nearby_providers(role, lat, lng, radius_km=None):
    """
    Return providers of the given role sorted by distance.
    - If driver has GPS (lat/lng): show all providers within radius_km,
      plus ALL providers with no GPS coords (they show as "Nearby").
    - If driver has no GPS: show ALL active+available providers.
    - radius_km default is 50 km to avoid providers being hidden on a
      platform still growing its user base.
    """
    from app import db
    if radius_km is None:
        radius_km = current_app.config.get("NEARBY_RADIUS_KM", 50)

    # Base query — active and available (no GPS filter here)
    users = (
        User.query
        .filter_by(role=role, is_active=True, is_available=True)
        .all()
    )

    results = []
    for u in users:
        if lat is not None and lng is not None and u.location_lat and u.location_lng:
            # Both driver and provider have GPS — apply radius filter
            dist = haversine_km(lat, lng, u.location_lat, u.location_lng)
            if dist <= radius_km:
                d = u.to_dict()
                d["distance"] = round(dist, 2)
                results.append(d)
        else:
            # Either driver or provider has no GPS — show anyway, no distance
            d = u.to_dict()
            d["distance"] = None
            results.append(d)

    # Sort: providers with distance first (closest first), then no-GPS providers
    with_dist    = sorted([r for r in results if r["distance"] is not None], key=lambda x: x["distance"])
    without_dist = [r for r in results if r["distance"] is None]
    return with_dist + without_dist
