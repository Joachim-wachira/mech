"""
Mech Platform — Authentication Blueprint
Handles:
  - Driver / Mechanic / SpareShop registration
  - Login (email OR phone + password)
  - Forgot password (OTP via SMS)
  - Reset password (validate OTP + set new password)
  - SMS phone verification
  - Current-user lookup (/me)

Registered in __init__.py at:  url_prefix="/api/auth"
"""
import json
import secrets
from datetime import datetime, timedelta, timezone
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from marshmallow import ValidationError

from app import db
from app.models import User, MechanicProfile, SpareShopProfile, SmsVerification
from app.schemas import (
    DriverRegistrationSchema,
    MechanicRegistrationSchema,
    SpareShopRegistrationSchema,
    SendSmsSchema,
    VerifySmsSchema,
)
from app.utils import generate_sms_code, success_response, error_response
from app.sms_service import send_sms

auth_bp = Blueprint("auth", __name__)

# ── In-memory OTP store for password reset ────────────────────────
# Maps identifier (phone/email) → { code, expires_at, user_id }
# In production swap this for a Redis key or a DB table column.
_otp_store: dict = {}
OTP_TTL_MINUTES = 15


# ── Helper ───────────────────────────────────────────────────────
def _auth_response(user, status=201):
    """Build a standard JWT login response."""
    token = create_access_token(
        identity=str(user.id),
        expires_delta=timedelta(days=30),
    )
    return success_response(
        {"token": token, "user": user.to_dict(), "role": user.role},
        status=status,
    )


def _normalize(identifier: str) -> str:
    """Lowercase + strip an email or phone for consistent lookup."""
    return identifier.strip().lower()


# ── Driver Registration ──────────────────────────────────────────
@auth_bp.route("/register/driver", methods=["POST"])
def register_driver():
    schema = DriverRegistrationSchema()
    try:
        data = schema.load(request.get_json(force=True) or {})
    except ValidationError as e:
        # Flatten validation errors into a readable string for the frontend
        msgs = e.messages
        flat = "; ".join(
            f"{k}: {v[0] if isinstance(v, list) else v}"
            for k, v in msgs.items()
        ) if isinstance(msgs, dict) else str(msgs)
        return error_response(flat, 422)

    if User.query.filter_by(email=data["email"]).first():
        return error_response("Email already registered", 409)
    if User.query.filter_by(phone=data["phone"]).first():
        return error_response("Phone already registered", 409)

    user = User(
        full_name     = data["full_name"],
        email         = data["email"],
        phone         = data["phone"],
        role          = "driver",
        location_text = data.get("location_text", ""),
        location_lat  = data.get("location_lat"),
        location_lng  = data.get("location_lng"),
    )
    user.set_password(data["password"])
    db.session.add(user)
    db.session.commit()
    return _auth_response(user)


# ── Mechanic Registration ────────────────────────────────────────
@auth_bp.route("/register/mechanic", methods=["POST"])
def register_mechanic():
    schema = MechanicRegistrationSchema()
    try:
        data = schema.load(request.get_json(force=True) or {})
    except ValidationError as e:
        msgs = e.messages
        flat = "; ".join(
            f"{k}: {v[0] if isinstance(v, list) else v}"
            for k, v in msgs.items()
        ) if isinstance(msgs, dict) else str(msgs)
        return error_response(flat, 422)

    if User.query.filter_by(email=data["email"]).first():
        return error_response("Email already registered", 409)
    if User.query.filter_by(phone=data["phone"]).first():
        return error_response("Phone already registered", 409)

    user = User(
        full_name     = data["full_name"],
        email         = data["email"],
        phone         = data["phone"],
        role          = "mechanic",
        business_name = data.get("business_name", ""),
        location_text = data.get("location_text", ""),
        location_lat  = data.get("location_lat"),
        location_lng  = data.get("location_lng"),
    )
    user.set_password(data["password"])
    db.session.add(user)
    db.session.flush()

    profile = MechanicProfile(
        user_id        = user.id,
        vehicle_brands = json.dumps(data.get("vehicle_brands", [])),
        services       = json.dumps(data.get("services", [])),
    )
    db.session.add(profile)
    db.session.commit()
    return _auth_response(user)


# ── Spare Shop Registration ──────────────────────────────────────
@auth_bp.route("/register/spareshop", methods=["POST"])
def register_spareshop():
    schema = SpareShopRegistrationSchema()
    try:
        data = schema.load(request.get_json(force=True) or {})
    except ValidationError as e:
        msgs = e.messages
        flat = "; ".join(
            f"{k}: {v[0] if isinstance(v, list) else v}"
            for k, v in msgs.items()
        ) if isinstance(msgs, dict) else str(msgs)
        return error_response(flat, 422)

    if User.query.filter_by(email=data["email"]).first():
        return error_response("Email already registered", 409)
    if User.query.filter_by(phone=data["phone"]).first():
        return error_response("Phone already registered", 409)

    user = User(
        full_name     = data["full_name"],
        email         = data["email"],
        phone         = data["phone"],
        role          = "spareshop",
        business_name = data.get("business_name", ""),
        location_text = data.get("location_text", ""),
        location_lat  = data.get("location_lat"),
        location_lng  = data.get("location_lng"),
    )
    user.set_password(data["password"])
    db.session.add(user)
    db.session.flush()

    profile = SpareShopProfile(
        user_id              = user.id,
        inventory_categories = json.dumps(data.get("inventory_categories", [])),
        delivery_options     = json.dumps(data.get("delivery_options", [])),
        delivery_km          = data.get("delivery_km"),
    )
    db.session.add(profile)
    db.session.commit()
    return _auth_response(user)


# ── Login (email OR phone + password) ────────────────────────────
@auth_bp.route("/login", methods=["POST"])
def login():
    data       = request.get_json(force=True) or {}
    # Support both {"email":…,"password":…} and {"identifier":…,"password":…}
    identifier = _normalize(data.get("identifier") or data.get("email") or "")
    password   = data.get("password", "")

    if not identifier or not password:
        return error_response("Phone/email and password are required", 400)

    user = (
        User.query.filter_by(email=identifier).first() or
        User.query.filter_by(phone=identifier).first()
    )

    if not user or not user.check_password(password):
        return error_response("Invalid credentials", 401)
    if not user.is_active:
        return error_response("Account deactivated — contact admin", 403)
    if (user.is_suspended and user.suspended_until
            and user.suspended_until > datetime.utcnow()):
        return error_response(
            f"Account suspended until {user.suspended_until.isoformat()}", 403
        )

    user.last_seen = datetime.utcnow()
    db.session.commit()
    return _auth_response(user, status=200)


# ── Current User ─────────────────────────────────────────────────
@auth_bp.route("/me", methods=["GET"])
@jwt_required()
def me():
    user_id = get_jwt_identity()
    user    = User.query.get_or_404(user_id)
    return success_response({"user": user.to_dict()})


# ── Logout (stateless — client drops token) ──────────────────────
@auth_bp.route("/logout", methods=["POST"])
@jwt_required()
def logout():
    return success_response({"message": "Logged out successfully"})


# ── Send SMS Verification ────────────────────────────────────────
@auth_bp.route("/send-sms", methods=["POST"])
def send_sms_code():
    schema = SendSmsSchema()
    try:
        data = schema.load(request.get_json(force=True) or {})
    except ValidationError as e:
        msgs = e.messages
        flat = "; ".join(
            f"{k}: {v[0] if isinstance(v, list) else v}"
            for k, v in msgs.items()
        ) if isinstance(msgs, dict) else str(msgs)
        return error_response(flat, 422)

    phone      = data["phone"]
    code       = generate_sms_code()
    expires_at = datetime.utcnow() + timedelta(minutes=10)

    SmsVerification.query.filter_by(phone=phone, is_used=False).update({"is_used": True})

    verification = SmsVerification(phone=phone, code=code, expires_at=expires_at)
    db.session.add(verification)
    db.session.commit()

    send_sms(phone, f"Your Mech verification code is: {code}. Valid for 10 minutes.")
    return success_response({"message": f"SMS code sent to {phone}"})


# ── Verify SMS Code ──────────────────────────────────────────────
@auth_bp.route("/verify-sms", methods=["POST"])
def verify_sms_code():
    schema = VerifySmsSchema()
    try:
        data = schema.load(request.get_json(force=True) or {})
    except ValidationError as e:
        msgs = e.messages
        flat = "; ".join(
            f"{k}: {v[0] if isinstance(v, list) else v}"
            for k, v in msgs.items()
        ) if isinstance(msgs, dict) else str(msgs)
        return error_response(flat, 422)

    phone, code = data["phone"], data["code"]
    record = (
        SmsVerification.query
        .filter_by(phone=phone, code=code, is_used=False)
        .order_by(SmsVerification.created_at.desc())
        .first()
    )

    if not record:
        return error_response("Invalid verification code", 400)
    if record.expires_at < datetime.utcnow():
        return error_response("Verification code expired", 400)

    record.is_used = True
    user = User.query.filter_by(phone=phone).first()
    if user:
        user.phone_verified = True
    db.session.commit()

    return success_response({"verified": True, "message": "Phone verified successfully"})


# ── Forgot Password — send OTP ───────────────────────────────────
@auth_bp.route("/forgot-password", methods=["POST"])
def forgot_password():
    data       = request.get_json(silent=True) or {}
    identifier = _normalize(data.get("identifier", ""))

    if not identifier:
        return error_response("Phone number or email is required", 400)

    user = (
        User.query.filter_by(email=identifier).first() or
        User.query.filter_by(phone=identifier).first()
    )

    # Generic response prevents user enumeration
    if not user:
        return success_response({"message": "If that account exists, a reset code has been sent."})

    code       = str(secrets.randbelow(900000) + 100000)   # 6-digit OTP
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=OTP_TTL_MINUTES)

    _otp_store[identifier] = {
        "code":       code,
        "expires_at": expires_at,
        "user_id":    user.id,
    }

    msg = f"Your mech password reset code is: {code}. Valid for {OTP_TTL_MINUTES} minutes."

    if "@" in identifier:
        # Email OTP — log for now; wire up real email provider later
        current_app.logger.info(f"[forgot-password] Email OTP for {identifier}: {code}")
    else:
        send_sms(user.phone, msg)

    return success_response({"message": "If that account exists, a reset code has been sent."})


# ── Reset Password — validate OTP + set new password ─────────────
@auth_bp.route("/reset-password", methods=["POST"])
def reset_password():
    data       = request.get_json(silent=True) or {}
    identifier = _normalize(data.get("identifier", ""))
    code       = str(data.get("code", "")).strip()
    new_pw     = data.get("new_password", "")

    if not identifier or not code or not new_pw:
        return error_response("identifier, code and new_password are required", 400)
    if len(new_pw) < 8:
        return error_response("Password must be at least 8 characters", 400)

    record = _otp_store.get(identifier)
    if not record:
        return error_response("No reset code found — please request a new one", 400)
    if datetime.now(timezone.utc) > record["expires_at"]:
        _otp_store.pop(identifier, None)
        return error_response("Reset code expired — please request a new one", 400)
    if record["code"] != code:
        return error_response("Invalid reset code", 400)

    user = User.query.get(record["user_id"])
    if not user:
        return error_response("User not found", 404)

    user.set_password(new_pw)
    try:
        db.session.commit()
        _otp_store.pop(identifier, None)
        return success_response({"message": "Password reset successfully — you can now login"})
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error(f"[reset-password] {exc}")
        return error_response("Could not reset password — try again", 500)
