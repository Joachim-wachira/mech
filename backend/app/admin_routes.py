"""
Mech Platform — Admin API Routes Blueprint
Handles: User management, Verification, Conversation logs, System status
"""
from datetime import datetime, timedelta
from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from app import db
from app.models import (
    User, Conversation, Message, Notification,
    AdminAction, IssueReport, CallLog, Review, Transaction
)
from app.utils import success_response, error_response, role_required, current_user, paginate_query, notify_via_chat
from app.sms_service import send_sms

admin_bp = Blueprint("admin", __name__)


def _log_action(admin_id, target_id, action, notes=""):
    entry = AdminAction(admin_id=admin_id, target_user_id=target_id, action=action, notes=notes)
    db.session.add(entry)


# ── Stats Overview ────────────────────────────────────────────────
@admin_bp.route("/stats", methods=["GET"])
@jwt_required()
def get_stats():
    user = current_user()
    if not user or user.role != "admin":
        return error_response("Admin access required", 403)

    total_users = User.query.filter(User.role != "admin").count()
    mechanics = User.query.filter_by(role="mechanic").count()
    spare_shops = User.query.filter_by(role="spareshop").count()
    drivers = User.query.filter_by(role="driver").count()

    pending_mechanic = User.query.filter_by(role="mechanic", is_verified=False, is_active=True).count()
    pending_shop = User.query.filter_by(role="spareshop", is_verified=False, is_active=True).count()

    avg_rating_result = db.session.query(db.func.avg(Review.rating)).scalar()
    avg_rating = round(float(avg_rating_result or 0), 1)

    total_earnings = db.session.query(db.func.sum(Transaction.amount_kes)).filter_by(status="completed").scalar() or 0

    return success_response({
        "total_users": total_users,
        "mechanics": mechanics,
        "spare_shops": spare_shops,
        "drivers": drivers,
        "pending_mechanic_verifications": pending_mechanic,
        "pending_shop_verifications": pending_shop,
        "avg_rating": avg_rating,
        "total_earnings_kes": total_earnings,
    })


# ── User List ─────────────────────────────────────────────────────
@admin_bp.route("/users", methods=["GET"])
@jwt_required()
def list_users():
    user = current_user()
    if not user or user.role != "admin":
        return error_response("Admin access required", 403)

    role = request.args.get("role")
    search = request.args.get("q")
    page = int(request.args.get("page", 1))

    q = User.query.filter(User.role != "admin")
    if role:
        q = q.filter_by(role=role)
    if search:
        q = q.filter(
            (User.full_name.ilike(f"%{search}%")) |
            (User.email.ilike(f"%{search}%")) |
            (User.phone.ilike(f"%{search}%"))
        )
    q = q.order_by(User.created_at.desc())

    result = paginate_query(q, page)
    users = [u.to_dict() for u in result["items"]]
    return success_response({"users": users, "total": result["total"], "page": page})


# ── Verification Queue ────────────────────────────────────────────
@admin_bp.route("/verification-queue", methods=["GET"])
@jwt_required()
def verification_queue():
    user = current_user()
    if not user or user.role != "admin":
        return error_response("Admin access required", 403)

    role = request.args.get("role", "mechanic")
    page = int(request.args.get("page", 1))

    q = User.query.filter_by(role=role, is_verified=False, is_active=True).order_by(User.created_at)
    result = paginate_query(q, page)
    users = [u.to_dict() for u in result["items"]]
    return success_response({"users": users, "total": result["total"]})


@admin_bp.route("/verify/<int:target_id>", methods=["POST"])
@jwt_required()
def verify_user(target_id):
    admin = current_user()
    if not admin or admin.role != "admin":
        return error_response("Admin access required", 403)

    data = request.get_json(force=True) or {}
    approved = data.get("approved", True)

    target = User.query.get_or_404(target_id)
    target.is_verified = approved
    _log_action(admin.id, target_id, "verify" if approved else "reject_verify", notes=data.get("notes", ""))
    db.session.commit()

    # Notify user
    notif = Notification(
        user_id=target_id,
        message="Your account has been verified!" if approved else "Your verification was not approved.",
        notification_type="verification",
    )
    db.session.add(notif)
    db.session.commit()

    from app import socketio
    socketio.emit("notification", {"message": notif.message}, room=f"user_{target_id}")

    return success_response({"message": "Verification updated", "verified": approved})


# ── Suspend ───────────────────────────────────────────────────────
@admin_bp.route("/suspend", methods=["POST"])
@jwt_required()
def suspend_user():
    admin = current_user()
    if not admin or admin.role != "admin":
        return error_response("Admin access required", 403)

    data = request.get_json(force=True) or {}
    user_id = data.get("user_id")
    duration_hours = int(data.get("duration", 24))

    if not user_id:
        return error_response("user_id required")

    target = User.query.get_or_404(user_id)
    target.is_suspended = True
    target.suspended_until = datetime.utcnow() + timedelta(hours=duration_hours)

    notify_via_chat(user_id, f"Your account has been suspended for {duration_hours} hours.", "suspension")

    _log_action(admin.id, user_id, "suspend", notes=f"Duration: {duration_hours}h")
    db.session.commit()

    return success_response({"message": f"User suspended for {duration_hours} hours"})


# ── Deactivate ────────────────────────────────────────────────────
@admin_bp.route("/deactivate", methods=["POST"])
@jwt_required()
def deactivate_user():
    admin = current_user()
    if not admin or admin.role != "admin":
        return error_response("Admin access required", 403)

    data = request.get_json(force=True) or {}
    user_id = data.get("user_id")
    if not user_id:
        return error_response("user_id required")

    target = User.query.get_or_404(user_id)
    target.is_active = False

    _log_action(admin.id, user_id, "deactivate")
    db.session.commit()

    return success_response({"message": "User account deactivated"})


# ── Toggle Active (re-activate / deactivate) ──────────────────────
@admin_bp.route("/users/<int:user_id>/toggle-active", methods=["POST"])
@jwt_required()
def toggle_user_active(user_id):
    """Flip is_active. Used by the dashboard Activate/Deactivate button
    so re-activating a previously-deactivated account actually works
    (the old /deactivate endpoint could only ever set it to False)."""
    admin = current_user()
    if not admin or admin.role != "admin":
        return error_response("Admin access required", 403)

    target = User.query.get_or_404(user_id)
    target.is_active = not target.is_active

    _log_action(admin.id, user_id, "activate" if target.is_active else "deactivate")
    db.session.commit()

    state = "activated" if target.is_active else "deactivated"
    return success_response({"message": f"{target.full_name}'s account {state}.", "is_active": target.is_active})


# ── Lock / Unlock Account ──────────────────────────────────────────
@admin_bp.route("/users/<int:user_id>/lock", methods=["POST"])
@jwt_required()
def lock_account(user_id):
    """
    Lock a provider's account (e.g. for an expired subscription that
    hasn't been handled via the subscriptions flow, or any other
    reason). Body: { reason }
    """
    admin = current_user()
    if not admin or admin.role != "admin":
        return error_response("Admin access required", 403)

    target = User.query.get_or_404(user_id)
    data   = request.get_json(force=True) or {}
    reason = data.get("reason", "Account locked by admin.")

    target.is_suspended    = True
    target.suspended_until = None  # indefinite, until admin unlocks

    notify_via_chat(user_id, f"Your account has been locked. Reason: {reason}", "account_locked")

    _log_action(admin.id, user_id, "lock_account", notes=reason)
    db.session.commit()

    return success_response({"message": f"{target.full_name}'s account locked."})


@admin_bp.route("/users/<int:user_id>/unlock", methods=["POST"])
@jwt_required()
def unlock_account(user_id):
    """Unlock a previously-locked account (e.g. after the provider pays)."""
    admin = current_user()
    if not admin or admin.role != "admin":
        return error_response("Admin access required", 403)

    target = User.query.get_or_404(user_id)
    target.is_suspended    = False
    target.suspended_until = None

    notify_via_chat(user_id, "Your account has been unlocked. Welcome back!", "account_unlocked")

    _log_action(admin.id, user_id, "unlock_account")
    db.session.commit()

    return success_response({"message": f"{target.full_name}'s account unlocked."})


# ── Admin Update Profile ──────────────────────────────────────────
@admin_bp.route("/users/<int:user_id>", methods=["PUT"])
@jwt_required()
def admin_update_user(user_id):
    admin = current_user()
    if not admin or admin.role != "admin":
        return error_response("Admin access required", 403)

    target = User.query.get_or_404(user_id)
    data = request.get_json(force=True) or {}
    allowed = ["full_name", "email", "phone", "business_name", "location_text", "role", "is_verified", "is_active"]
    for field in allowed:
        if field in data:
            setattr(target, field, data[field])

    _log_action(admin.id, user_id, "update_profile")
    db.session.commit()

    return success_response({"user": target.to_dict(), "message": "User updated"})


# ── Conversation Logs ─────────────────────────────────────────────
@admin_bp.route("/conversations", methods=["GET"])
@jwt_required()
def get_conversation_logs():
    admin = current_user()
    if not admin or admin.role != "admin":
        return error_response("Admin access required", 403)

    page = int(request.args.get("page", 1))
    q = Conversation.query.order_by(Conversation.updated_at.desc())
    result = paginate_query(q, page)

    logs = []
    for c in result["items"]:
        parts = [p.user_id for p in c.participants]
        last_msg = c.messages.order_by(Message.created_at.desc()).first()
        logs.append({
            "id": c.id,
            "is_group": c.is_group,
            "group_name": c.group_name,
            "participant_ids": parts,
            "last_message": last_msg.content if last_msg else "",
            "updated_at": c.updated_at.isoformat(),
        })

    return success_response({"conversations": logs, "total": result["total"]})


@admin_bp.route("/conversations/<int:conv_id>/messages", methods=["GET"])
@jwt_required()
def admin_view_conversation(conv_id):
    admin = current_user()
    if not admin or admin.role != "admin":
        return error_response("Admin access required", 403)

    page = int(request.args.get("page", 1))
    q = Message.query.filter_by(conversation_id=conv_id).order_by(Message.created_at.asc())
    result = paginate_query(q, page, per_page=100)
    msgs = [m.to_dict() for m in result["items"]]
    return success_response({"messages": msgs, "total": result["total"]})


# ── Admin Notifications ───────────────────────────────────────────
@admin_bp.route("/notify", methods=["POST"])
@jwt_required()
def send_notification():
    """
    Send a notification to one user, all users of a role, or everyone.
    Each notification is ALSO delivered as a chat message from the
    "Mech Admin" system account, so it appears in the recipient's
    chat list with sender "Mech Admin". Replies to that conversation
    are blocked server-side (see send_message_rest in routes.py).
    """
    admin = current_user()
    if not admin or admin.role != "admin":
        return error_response("Admin access required", 403)

    data = request.get_json(force=True) or {}
    message = data.get("message", "").strip()
    target_email = data.get("target")
    role = data.get("role")
    broadcast = data.get("broadcast", False)

    if not message:
        return error_response("Message is required")

    recipients = []
    if broadcast:
        recipients = User.query.filter(User.role != "admin", User.is_active == True).all()
    elif role:
        recipients = User.query.filter_by(role=role, is_active=True).all()
    elif target_email:
        u = User.query.filter_by(email=target_email).first()
        if u:
            recipients = [u]

    if not recipients:
        return error_response("No matching recipients found", 404)

    for u in recipients:
        notify_via_chat(u.id, message, "admin")

    _log_action(admin.id, None, "send_notification",
                notes=f"\"{message[:80]}\" → {len(recipients)} recipient(s) "
                      f"({'broadcast' if broadcast else role or target_email})")
    db.session.commit()
    return success_response({"message": f"Notification sent to {len(recipients)} user(s)"})



# ── System Status ─────────────────────────────────────────────────
@admin_bp.route("/system-status", methods=["GET"])
@jwt_required()
def system_status():
    admin = current_user()
    if not admin or admin.role != "admin":
        return error_response("Admin access required", 403)

    # Ping DB
    db_ok = True
    try:
        db.session.execute(db.text("SELECT 1"))
    except Exception:
        db_ok = False

    # Ping SMS
    from app.sms_service import sms_status
    sms_ok = sms_status()

    statuses = [
        {"name": "api", "ok": True},
        {"name": "database", "ok": db_ok},
        {"name": "sms", "ok": sms_ok},
    ]

    return success_response({"statuses": statuses})


# ── Admin Actions History (Audit Trail) ────────────────────────────
@admin_bp.route("/actions", methods=["GET"])
@jwt_required()
def list_actions():
    """
    Audit trail of admin actions. Each entry shows WHICH admin
    performed the action and on WHICH user, so multiple admins can
    see each other's changes.
    """
    admin = current_user()
    if not admin or admin.role != "admin":
        return error_response("Admin access required", 403)

    page = int(request.args.get("page", 1))
    q = AdminAction.query.order_by(AdminAction.created_at.desc())
    result = paginate_query(q, page)

    # Batch-load admin/target names to avoid N+1 queries
    user_ids = set()
    for a in result["items"]:
        if a.admin_id: user_ids.add(a.admin_id)
        if a.target_user_id: user_ids.add(a.target_user_id)
    name_map = {u.id: u.full_name for u in User.query.filter(User.id.in_(user_ids)).all()} if user_ids else {}

    actions = [
        {
            "id": a.id,
            "admin_id": a.admin_id,
            "admin_name": name_map.get(a.admin_id, "Unknown admin"),
            "target_user_id": a.target_user_id,
            "target_name": name_map.get(a.target_user_id) if a.target_user_id else None,
            "action": a.action,
            "notes": a.notes,
            "created_at": a.created_at.isoformat(),
        }
        for a in result["items"]
    ]
    return success_response({"actions": actions, "total": result["total"]})


# ── Issue Reports ─────────────────────────────────────────────────
@admin_bp.route("/issues", methods=["GET"])
@jwt_required()
def list_issues():
    admin = current_user()
    if not admin or admin.role != "admin":
        return error_response("Admin access required", 403)

    page = int(request.args.get("page", 1))
    status = request.args.get("status", "open")
    q = IssueReport.query.filter_by(status=status).order_by(IssueReport.created_at.desc())
    result = paginate_query(q, page)
    issues = [
        {"id": i.id, "user_id": i.user_id, "description": i.description, "status": i.status, "created_at": i.created_at.isoformat()}
        for i in result["items"]
    ]
    return success_response({"issues": issues, "total": result["total"]})


@admin_bp.route("/issues/<int:issue_id>/resolve", methods=["POST"])
@jwt_required()
def resolve_issue(issue_id):
    admin = current_user()
    if not admin or admin.role != "admin":
        return error_response("Admin access required", 403)

    issue = IssueReport.query.get_or_404(issue_id)
    issue.status = "resolved"
    db.session.commit()
    return success_response({"message": "Issue resolved"})


# ── Create Another Admin ──────────────────────────────────────────
@admin_bp.route("/create-admin", methods=["POST"])
@jwt_required()
def create_admin():
    """
    Allows an existing admin to create additional admin accounts.
    POST /api/admin/create-admin
    Body: { full_name, email, phone, password }
    """
    admin = current_user()
    if not admin or admin.role != "admin":
        return error_response("Admin access required", 403)

    data = request.get_json(force=True) or {}
    full_name = (data.get("full_name") or "").strip()
    email     = (data.get("email") or "").strip().lower()
    phone     = (data.get("phone") or "").strip()
    password  = data.get("password", "")

    if not all([full_name, email, phone, password]):
        return error_response("full_name, email, phone and password are all required", 400)
    if len(password) < 8:
        return error_response("Password must be at least 8 characters", 400)

    if User.query.filter_by(email=email).first():
        return error_response("Email already registered", 409)
    if User.query.filter_by(phone=phone).first():
        return error_response("Phone already registered", 409)

    from werkzeug.security import generate_password_hash
    new_admin = User(
        full_name    = full_name,
        email        = email,
        phone        = phone,
        role         = "admin",
        is_verified  = True,
        is_active    = True,
        phone_verified = True,
    )
    new_admin.password_hash = generate_password_hash(password)
    db.session.add(new_admin)

    _log_action(admin.id, None, "create_admin", notes=f"Created admin: {email}")
    db.session.commit()

    return success_response({
        "message": f"Admin account created for {email}",
        "user": new_admin.to_dict()
    }, status=201)


# ── List All Admins ───────────────────────────────────────────────
@admin_bp.route("/admins", methods=["GET"])
@jwt_required()
def list_admins():
    """Returns all admin accounts so you can see who has access."""
    admin = current_user()
    if not admin or admin.role != "admin":
        return error_response("Admin access required", 403)

    admins = User.query.filter_by(role="admin", is_system=False).order_by(User.created_at).all()
    return success_response({"admins": [a.to_dict() for a in admins]})


# ── Remove Admin Role ─────────────────────────────────────────────
@admin_bp.route("/remove-admin/<int:target_id>", methods=["POST"])
@jwt_required()
def remove_admin(target_id):
    """
    Demotes an admin account to 'driver' role (does not delete the account).
    An admin cannot remove themselves.
    POST /api/admin/remove-admin/<id>
    """
    admin = current_user()
    if not admin or admin.role != "admin":
        return error_response("Admin access required", 403)

    if admin.id == target_id:
        return error_response("You cannot remove your own admin access", 400)

    target = User.query.get_or_404(target_id)
    if target.role != "admin":
        return error_response("That user is not an admin", 400)
    if target.is_system:
        return error_response("Cannot modify the Mech Admin system account", 400)

    # Demote to driver — keeps the account intact, just strips admin access
    target.role = "driver"
    _log_action(admin.id, target_id, "remove_admin", notes=f"Removed admin role from {target.email}")
    db.session.commit()

    return success_response({"message": f"Admin access removed for {target.email}"})
