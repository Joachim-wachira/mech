"""
Mech Platform — Authentication Blueprint
Handles: Driver/Mechanic/SpareShop registration, login, SMS verification
"""
import json
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from marshmallow import ValidationError

from app import db
from app.models import User, MechanicProfile, SpareShopProfile, SmsVerification
from app.schemas import (
    DriverRegistrationSchema,
    MechanicRegistrationSchema,
    SpareShopRegistrationSchema,
    LoginSchema,
    SendSmsSchema,
    VerifySmsSchema,
)
from app.utils import generate_sms_code, success_response, error_response
from app.sms_service import send_sms

auth_bp = Blueprint("auth", __name__)


# ── Helper: build JWT response ──────────────────────────────────
def _auth_response(user):
    token = create_access_token(identity=user.id)
    return success_response(
        {
            "token": token,
            "user": user.to_dict(),
            "role": user.role,
        },
        status=201,
    )


# ── Driver Registration ─────────────────────────────────────────
@auth_bp.route("/register/driver", methods=["POST"])
def register_driver():
    schema = DriverRegistrationSchema()
    try:
        data = schema.load(request.get_json(force=True) or {})
    except ValidationError as e:
        return error_response(str(e.messages))

    if User.query.filter_by(email=data["email"]).first():
        return error_response("Email already registered", 409)
    if User.query.filter_by(phone=data["phone"]).first():
        return error_response("Phone already registered", 409)

    user = User(
        full_name=data["full_name"],
        email=data["email"],
        phone=data["phone"],
        role="driver",
        location_text=data.get("location_text", ""),
        location_lat=data.get("location_lat"),
        location_lng=data.get("location_lng"),
    )
    user.set_password(data["password"])

    db.session.add(user)
    db.session.commit()
    return _auth_response(user)


# ── Mechanic Registration ───────────────────────────────────────
@auth_bp.route("/register/mechanic", methods=["POST"])
def register_mechanic():
    schema = MechanicRegistrationSchema()
    try:
        data = schema.load(request.get_json(force=True) or {})
    except ValidationError as e:
        return error_response(str(e.messages))

    if User.query.filter_by(email=data["email"]).first():
        return error_response("Email already registered", 409)
    if User.query.filter_by(phone=data["phone"]).first():
        return error_response("Phone already registered", 409)

    user = User(
        full_name=data["full_name"],
        email=data["email"],
        phone=data["phone"],
        role="mechanic",
        business_name=data.get("business_name", ""),
        location_text=data.get("location_text", ""),
        location_lat=data.get("location_lat"),
        location_lng=data.get("location_lng"),
    )
    user.set_password(data["password"])
    db.session.add(user)
    db.session.flush()  # get user.id

    profile = MechanicProfile(
        user_id=user.id,
        vehicle_brands=json.dumps(data.get("vehicle_brands", [])),
        services=json.dumps(data.get("services", [])),
    )
    db.session.add(profile)
    db.session.commit()
    return _auth_response(user)


# ── Spare Shop Registration ─────────────────────────────────────
@auth_bp.route("/register/spareshop", methods=["POST"])
def register_spareshop():
    schema = SpareShopRegistrationSchema()
    try:
        data = schema.load(request.get_json(force=True) or {})
    except ValidationError as e:
        return error_response(str(e.messages))

    if User.query.filter_by(email=data["email"]).first():
        return error_response("Email already registered", 409)
    if User.query.filter_by(phone=data["phone"]).first():
        return error_response("Phone already registered", 409)

    user = User(
        full_name=data["full_name"],
        email=data["email"],
        phone=data["phone"],
        role="spareshop",
        business_name=data.get("business_name", ""),
        location_text=data.get("location_text", ""),
        location_lat=data.get("location_lat"),
        location_lng=data.get("location_lng"),
    )
    user.set_password(data["password"])
    db.session.add(user)
    db.session.flush()

    profile = SpareShopProfile(
        user_id=user.id,
        inventory_categories=json.dumps(data.get("inventory_categories", [])),
        delivery_options=json.dumps(data.get("delivery_options", [])),
        delivery_km=data.get("delivery_km"),
    )
    db.session.add(profile)
    db.session.commit()
    return _auth_response(user)


# ── Login ───────────────────────────────────────────────────────
@auth_bp.route("/login", methods=["POST"])
def login():
    schema = LoginSchema()
    try:
        data = schema.load(request.get_json(force=True) or {})
    except ValidationError as e:
        return error_response(str(e.messages))

    user = User.query.filter_by(email=data["email"]).first()
    if not user or not user.check_password(data["password"]):
        return error_response("Invalid credentials", 401)
    if not user.is_active:
        return error_response("Account deactivated", 403)
    if user.is_suspended and user.suspended_until and user.suspended_until > datetime.utcnow():
        return error_response(f"Account suspended until {user.suspended_until.isoformat()}", 403)

    user.last_seen = datetime.utcnow()
    db.session.commit()
    return _auth_response(user)


# ── Get current user ────────────────────────────────────────────
@auth_bp.route("/me", methods=["GET"])
@jwt_required()
def me():
    user_id = get_jwt_identity()
    user = User.query.get_or_404(user_id)
    return success_response({"user": user.to_dict()})


# ── Send SMS verification ───────────────────────────────────────
@auth_bp.route("/send-sms", methods=["POST"])
def send_sms_code():
    schema = SendSmsSchema()
    try:
        data = schema.load(request.get_json(force=True) or {})
    except ValidationError as e:
        return error_response(str(e.messages))

    phone = data["phone"]
    code = generate_sms_code()
    expires_at = datetime.utcnow() + timedelta(minutes=10)

    # Mark any previous codes as used
    SmsVerification.query.filter_by(phone=phone, is_used=False).update({"is_used": True})

    verification = SmsVerification(phone=phone, code=code, expires_at=expires_at)
    db.session.add(verification)
    db.session.commit()

    # Send via SMS service
    send_sms(phone, f"Your Mech verification code is: {code}. Valid for 10 minutes.")

    return success_response({"message": f"SMS code sent to {phone}"})


# ── Verify SMS code ─────────────────────────────────────────────
@auth_bp.route("/verify-sms", methods=["POST"])
def verify_sms_code():
    schema = VerifySmsSchema()
    try:
        data = schema.load(request.get_json(force=True) or {})
    except ValidationError as e:
        return error_response(str(e.messages))

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
    # Mark phone as verified if user exists
    user = User.query.filter_by(phone=phone).first()
    if user:
        user.phone_verified = True
    db.session.commit()

    return success_response({"verified": True, "message": "Phone verified successfully"})

"""
auth_extras.py
Additional auth endpoints: forgot-password, reset-password, login.
Merge these routes into your existing auth.py or register as a separate blueprint.

Mount with: app.register_blueprint(auth_extras_bp, url_prefix='/api/auth')
"""

import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from flask import Blueprint, jsonify, request, current_app
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity

auth_extras_bp = Blueprint('auth_extras', __name__)

# In-memory OTP store (replace with Redis or DB column in production)
_otp_store = {}   # { identifier: { code, expires_at, user_id } }

OTP_TTL_MINUTES = 15


def _get_models():
    from .models import db, User
    return db, User


def _send_sms(phone, message):
    """Send SMS via configured provider. Stub for development."""
    from .sms_service import send_sms as _send
    try:
        _send(phone, message)
    except Exception as exc:
        current_app.logger.warning(f"[auth_extras] SMS send failed: {exc}")


def _normalize(identifier):
    """Normalise phone or email for lookup."""
    return identifier.strip().lower()


# ─────────────────────────────────────────────────────────────────
# POST /api/auth/login
# Accepts phone OR email + password.
# ─────────────────────────────────────────────────────────────────
@auth_extras_bp.route('/login', methods=['POST'])
def login():
    db, User = _get_models()
    data       = request.get_json(silent=True) or {}
    identifier = _normalize(data.get('identifier', ''))
    password   = data.get('password', '')

    if not identifier or not password:
        return jsonify({"message": "Phone/email and password are required"}), 400

    # Try email first, then phone
    user = (User.query.filter_by(email=identifier).first() or
            User.query.filter_by(phone=identifier).first())

    if not user or not user.check_password(password):
        return jsonify({"message": "Invalid credentials"}), 401

    if not getattr(user, 'is_active', True):
        return jsonify({"message": "Account suspended. Contact admin."}), 403

    token = create_access_token(identity=str(user.id), expires_delta=timedelta(days=30))
    return jsonify({
        "token": token,
        "role":  user.role,
        "user":  {
            "id":        user.id,
            "full_name": user.full_name,
            "email":     user.email,
            "phone":     user.phone,
            "role":      user.role,
        }
    }), 200


# ─────────────────────────────────────────────────────────────────
# POST /api/auth/forgot-password
# Generates a 6-digit OTP and sends it via SMS / email.
# ─────────────────────────────────────────────────────────────────
@auth_extras_bp.route('/forgot-password', methods=['POST'])
def forgot_password():
    db, User = _get_models()
    data       = request.get_json(silent=True) or {}
    identifier = _normalize(data.get('identifier', ''))

    if not identifier:
        return jsonify({"message": "Phone number or email is required"}), 400

    user = (User.query.filter_by(email=identifier).first() or
            User.query.filter_by(phone=identifier).first())

    # Return generic success even if user not found (prevents user enumeration)
    if not user:
        return jsonify({"message": "If that account exists, a reset code has been sent."}), 200

    # Generate 6-digit OTP
    code       = str(secrets.randbelow(900000) + 100000)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=OTP_TTL_MINUTES)

    _otp_store[identifier] = {
        "code":       code,
        "expires_at": expires_at,
        "user_id":    user.id,
    }

    message = f"Your mech password reset code is: {code}. Valid for {OTP_TTL_MINUTES} minutes."

    if '@' in identifier:
        # TODO: swap for real email send
        current_app.logger.info(f"[forgot-password] Email OTP for {identifier}: {code}")
    else:
        _send_sms(user.phone, message)

    return jsonify({"message": "If that account exists, a reset code has been sent."}), 200


# ─────────────────────────────────────────────────────────────────
# POST /api/auth/reset-password
# Validates OTP and sets new password.
# ─────────────────────────────────────────────────────────────────
@auth_extras_bp.route('/reset-password', methods=['POST'])
def reset_password():
    db, User = _get_models()
    data       = request.get_json(silent=True) or {}
    identifier = _normalize(data.get('identifier', ''))
    code       = str(data.get('code', '')).strip()
    new_pw     = data.get('new_password', '')

    if not identifier or not code or not new_pw:
        return jsonify({"message": "identifier, code and new_password are required"}), 400

    if len(new_pw) < 8:
        return jsonify({"message": "Password must be at least 8 characters"}), 400

    record = _otp_store.get(identifier)
    if not record:
        return jsonify({"message": "No reset code found. Please request a new one."}), 400

    if datetime.now(timezone.utc) > record['expires_at']:
        _otp_store.pop(identifier, None)
        return jsonify({"message": "Reset code has expired. Please request a new one."}), 400

    if record['code'] != code:
        return jsonify({"message": "Invalid reset code."}), 400

    user = User.query.get(record['user_id'])
    if not user:
        return jsonify({"message": "User not found."}), 404

    user.set_password(new_pw)
    try:
        db.session.commit()
        _otp_store.pop(identifier, None)
        return jsonify({"message": "Password reset successfully. You can now login."}), 200
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error(f"[reset-password] {exc}")
        return jsonify({"message": "Could not reset password. Try again."}), 500


# ─────────────────────────────────────────────────────────────────
# POST /api/auth/logout  (optional — client just drops token)
# ─────────────────────────────────────────────────────────────────
@auth_extras_bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    # For stateless JWTs, logout is handled client-side.
    # Add token to a denylist here if you implement one.
    return jsonify({"message": "Logged out successfully"}), 200
