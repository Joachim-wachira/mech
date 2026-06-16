"""
Mech Platform — Subscription Routes Blueprint
Handles: subscription submission (provider side) + admin management of subscriptions

Endpoints (provider):
  POST /api/subscriptions/submit         Submit payment proof / request subscription
  GET  /api/subscriptions/my             Get own subscription status

Endpoints (admin):
  GET  /api/subscriptions/admin/all      All subscriptions with filters
  GET  /api/subscriptions/admin/queue    Pending payment verifications
  GET  /api/subscriptions/admin/expiring Subscriptions expiring within N days
  POST /api/subscriptions/admin/confirm/<id>    Confirm payment + activate
  POST /api/subscriptions/admin/reject/<id>     Reject payment proof
  POST /api/subscriptions/admin/grace/<id>      Grant grace period
  POST /api/subscriptions/admin/suspend/<id>    Suspend on expiry (no grace)
  POST /api/subscriptions/admin/notify-expiring Send renewal reminders
"""

from datetime import datetime, timedelta
from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from app import db
from app.models import User, Subscription, AdminAction, PLAN_DURATIONS, PLAN_PRICES_KES
from app.utils import success_response, error_response, current_user, paginate_query, notify_via_chat
from app.sms_service import send_sms

subscription_bp = Blueprint("subscriptions", __name__)


def _log_action(admin_id, target_id, action, notes=""):
    entry = AdminAction(admin_id=admin_id, target_user_id=target_id, action=action, notes=notes)
    db.session.add(entry)


def _notify(user_id, message, notification_type="subscription"):
    """Creates an in-app Notification AND a Mech Admin chat message
    (see utils.notify_via_chat for details)."""
    notify_via_chat(user_id, message, notification_type)


# ═══════════════════════════════════════════════════════════════════
# PROVIDER ROUTES
# ═══════════════════════════════════════════════════════════════════

@subscription_bp.route("/my", methods=["GET"])
@jwt_required()
def my_subscription():
    """Provider checks their own subscription status."""
    user = current_user()
    if not user or user.role not in ("mechanic", "spareshop"):
        return error_response("Only mechanics and spare shops have subscriptions", 403)

    sub = Subscription.query.filter_by(user_id=user.id).first()
    if not sub:
        # Auto-create an unpaid record so frontend can show plan options
        sub = Subscription(user_id=user.id, status="unpaid", plan="monthly")
        db.session.add(sub)
        db.session.commit()

    return success_response({
        "subscription": sub.to_dict(),
        "plans": {
            "monthly":  {"label": "1 Month",  "price_kes": PLAN_PRICES_KES["monthly"],  "days": PLAN_DURATIONS["monthly"]},
            "annual":   {"label": "1 Year",   "price_kes": PLAN_PRICES_KES["annual"],   "days": PLAN_DURATIONS["annual"]},
            "biennial": {"label": "5 Years",  "price_kes": PLAN_PRICES_KES["biennial"], "days": PLAN_DURATIONS["biennial"]},
        }
    })


@subscription_bp.route("/submit", methods=["POST"])
@jwt_required()
def submit_payment():
    """
    Provider submits payment intent / proof.
    Body: { plan, payment_ref, proof_url, payment_method }
    After submission, status becomes 'pending_verification' for admin review.
    """
    user = current_user()
    if not user or user.role not in ("mechanic", "spareshop"):
        return error_response("Only mechanics and spare shops can subscribe", 403)

    data = request.get_json(force=True) or {}
    plan = data.get("plan", "monthly")
    if plan not in PLAN_DURATIONS:
        return error_response("Invalid plan. Choose: monthly, annual, or biennial", 400)

    sub = Subscription.query.filter_by(user_id=user.id).first()
    if not sub:
        sub = Subscription(user_id=user.id)
        db.session.add(sub)

    # Block resubmission if already active
    if sub.status == "active" and sub.is_active:
        return error_response("Your subscription is already active", 400)

    sub.plan           = plan
    sub.amount_kes     = PLAN_PRICES_KES[plan]
    sub.payment_method = data.get("payment_method", "manual")
    sub.payment_ref    = (data.get("payment_ref") or "").strip() or None
    sub.proof_url      = (data.get("proof_url") or "").strip() or None
    sub.status         = "pending_verification"
    sub.updated_at     = datetime.utcnow()

    db.session.commit()

    return success_response({
        "message": "Payment submitted for admin review. You will be notified once confirmed.",
        "subscription": sub.to_dict(),
    }, status=201)


# ═══════════════════════════════════════════════════════════════════
# ADMIN ROUTES
# ═══════════════════════════════════════════════════════════════════

def _admin_guard():
    user = current_user()
    if not user or user.role != "admin":
        return None, error_response("Admin access required", 403)
    return user, None


@subscription_bp.route("/admin/all", methods=["GET"])
@jwt_required()
def admin_list_all():
    """All subscriptions. Filter by status or role."""
    admin, err = _admin_guard()
    if err:
        return err

    status_filter = request.args.get("status")   # active|expired|pending_verification|unpaid|grace|suspended
    role_filter   = request.args.get("role")      # mechanic|spareshop
    page          = int(request.args.get("page", 1))

    q = db.session.query(Subscription, User).join(User, Subscription.user_id == User.id)

    if role_filter:
        q = q.filter(User.role == role_filter)
    if status_filter:
        q = q.filter(Subscription.status == status_filter)

    q = q.order_by(Subscription.updated_at.desc())
    total = q.count()
    results = q.offset((page - 1) * 20).limit(20).all()

    items = []
    for sub, user in results:
        d = sub.to_dict()
        d["user"] = {
            "id": user.id, "full_name": user.full_name, "email": user.email,
            "phone": user.phone, "role": user.role, "business_name": user.business_name,
            "is_verified": user.is_verified,
        }
        items.append(d)

    return success_response({"subscriptions": items, "total": total, "page": page, "pages": (total + 19) // 20})


@subscription_bp.route("/admin/queue", methods=["GET"])
@jwt_required()
def admin_payment_queue():
    """Subscriptions pending payment verification — the admin approval queue."""
    admin, err = _admin_guard()
    if err:
        return err

    results = (
        db.session.query(Subscription, User)
        .join(User, Subscription.user_id == User.id)
        .filter(Subscription.status == "pending_verification")
        .order_by(Subscription.updated_at.asc())
        .all()
    )

    items = []
    for sub, user in results:
        d = sub.to_dict()
        d["user"] = {
            "id": user.id, "full_name": user.full_name, "email": user.email,
            "phone": user.phone, "role": user.role, "business_name": user.business_name,
        }
        items.append(d)

    return success_response({"queue": items, "count": len(items)})


@subscription_bp.route("/admin/expiring", methods=["GET"])
@jwt_required()
def admin_expiring():
    """Subscriptions expiring within N days (default 14). Used for renewal reminders."""
    admin, err = _admin_guard()
    if err:
        return err

    days = int(request.args.get("days", 14))
    cutoff = datetime.utcnow() + timedelta(days=days)

    results = (
        db.session.query(Subscription, User)
        .join(User, Subscription.user_id == User.id)
        .filter(
            Subscription.status == "active",
            Subscription.expires_at <= cutoff,
            Subscription.expires_at >= datetime.utcnow(),
        )
        .order_by(Subscription.expires_at.asc())
        .all()
    )

    items = []
    for sub, user in results:
        d = sub.to_dict()
        d["user"] = {
            "id": user.id, "full_name": user.full_name, "email": user.email,
            "phone": user.phone, "role": user.role, "business_name": user.business_name,
        }
        items.append(d)

    return success_response({"expiring": items, "count": len(items), "within_days": days})


@subscription_bp.route("/admin/confirm/<int:sub_id>", methods=["POST"])
@jwt_required()
def admin_confirm(sub_id):
    """
    Admin confirms a payment and activates the subscription.
    Body: { notes }   (optional)
    Sets: status=active, starts_at=now, expires_at=now+plan_days, is_verified=True on user
    """
    admin, err = _admin_guard()
    if err:
        return err

    sub = Subscription.query.get_or_404(sub_id)
    user = User.query.get_or_404(sub.user_id)

    if sub.status not in ("pending_verification", "unpaid", "expired", "suspended"):
        return error_response(f"Cannot confirm a subscription with status '{sub.status}'", 400)

    data = request.get_json(force=True) or {}
    now = datetime.utcnow()

    # If renewing an expired sub, start from now; otherwise start fresh
    start = now
    duration_days = PLAN_DURATIONS.get(sub.plan, 30)

    sub.status        = "active"
    sub.paid_at       = now
    sub.starts_at     = start
    sub.expires_at    = start + timedelta(days=duration_days)
    sub.grace_until   = None
    sub.confirmed_by  = admin.id
    sub.confirmed_at  = now
    sub.admin_notes   = data.get("notes", "")
    sub.notified_7d   = False
    sub.notified_1d   = False
    sub.updated_at    = now

    # Activate + verify the user account
    user.is_verified  = True
    user.is_suspended = False
    user.suspended_until = None

    # Notify the user
    plan_label = {"monthly": "1 Month", "annual": "1 Year", "biennial": "5 Years"}.get(sub.plan, sub.plan)
    msg = (f"Your {plan_label} Mech subscription has been activated! "
           f"It expires on {sub.expires_at.strftime('%d %b %Y')}. Welcome aboard.")
    _notify(user.id, msg, "subscription_activated")

    # Try SMS too
    try:
        send_sms(user.phone, msg)
    except Exception:
        pass

    _log_action(admin.id, user.id, "subscription_confirm",
                notes=f"Confirmed {sub.plan} plan. Expires {sub.expires_at.strftime('%Y-%m-%d')}")
    db.session.commit()

    return success_response({
        "message": f"Subscription activated for {user.full_name}. Expires {sub.expires_at.strftime('%d %b %Y')}.",
        "subscription": sub.to_dict(),
    })


@subscription_bp.route("/admin/reject/<int:sub_id>", methods=["POST"])
@jwt_required()
def admin_reject(sub_id):
    """
    Admin rejects a payment proof (e.g. invalid reference, wrong amount).
    Body: { reason }
    Resets status to 'unpaid' so user can resubmit.
    """
    admin, err = _admin_guard()
    if err:
        return err

    sub = Subscription.query.get_or_404(sub_id)
    user = User.query.get_or_404(sub.user_id)

    data = request.get_json(force=True) or {}
    reason = data.get("reason", "Payment could not be verified.")

    sub.status      = "unpaid"
    sub.admin_notes = reason
    sub.updated_at  = datetime.utcnow()

    msg = f"Your Mech subscription payment could not be verified. Reason: {reason}. Please resubmit with the correct M-Pesa reference."
    _notify(user.id, msg, "subscription_rejected")
    try:
        send_sms(user.phone, msg)
    except Exception:
        pass

    _log_action(admin.id, user.id, "subscription_reject", notes=reason)
    db.session.commit()

    return success_response({"message": f"Payment rejected and user notified. Reason: {reason}"})


@subscription_bp.route("/admin/grace/<int:sub_id>", methods=["POST"])
@jwt_required()
def admin_grant_grace(sub_id):
    """
    Admin grants a grace period to a provider whose subscription has expired (or is about to).
    Body: { period: "week" | "month", notes }
    """
    admin, err = _admin_guard()
    if err:
        return err

    sub = Subscription.query.get_or_404(sub_id)
    user = User.query.get_or_404(sub.user_id)

    data   = request.get_json(force=True) or {}
    period = data.get("period", "week")   # "week" or "month"

    if period not in ("week", "month"):
        return error_response("period must be 'week' or 'month'", 400)

    grace_days = 7 if period == "week" else 30
    now = datetime.utcnow()

    sub.status       = "grace"
    sub.grace_until  = now + timedelta(days=grace_days)
    sub.admin_notes  = data.get("notes", f"Grace period: 1 {period}")
    sub.updated_at   = now

    # Unsuspend so they can use the platform during grace
    user.is_suspended    = False
    user.suspended_until = None

    period_label = "1 week" if period == "week" else "1 month"
    msg = (f"Your Mech subscription has expired but an admin has granted you a free grace period of {period_label}. "
           f"Please renew before {sub.grace_until.strftime('%d %b %Y')} to avoid suspension.")
    _notify(user.id, msg, "subscription_grace")
    try:
        send_sms(user.phone, msg)
    except Exception:
        pass

    _log_action(admin.id, user.id, "subscription_grace",
                notes=f"Grace period: {period_label} until {sub.grace_until.strftime('%Y-%m-%d')}")
    db.session.commit()

    return success_response({
        "message": f"Grace period of {period_label} granted. Access until {sub.grace_until.strftime('%d %b %Y')}.",
        "subscription": sub.to_dict(),
    })


@subscription_bp.route("/admin/suspend/<int:sub_id>", methods=["POST"])
@jwt_required()
def admin_suspend_expired(sub_id):
    """
    Admin suspends a provider whose subscription has expired without granting grace.
    Body: { notes }
    """
    admin, err = _admin_guard()
    if err:
        return err

    sub = Subscription.query.get_or_404(sub_id)
    user = User.query.get_or_404(sub.user_id)

    data = request.get_json(force=True) or {}

    sub.status     = "suspended"
    sub.grace_until = None
    sub.admin_notes = data.get("notes", "Suspended due to expired subscription.")
    sub.updated_at  = datetime.utcnow()

    user.is_suspended    = True
    user.suspended_until = None   # Indefinite — lifts when subscription is renewed
    user.is_verified     = False  # Remove from public listings

    msg = ("Your Mech platform subscription has expired and your account has been suspended. "
           "Please renew your subscription to regain full access.")
    _notify(user.id, msg, "subscription_suspended")
    try:
        send_sms(user.phone, msg)
    except Exception:
        pass

    _log_action(admin.id, user.id, "subscription_suspend",
                notes=data.get("notes", "Expired subscription — no grace granted"))
    db.session.commit()

    return success_response({"message": f"{user.full_name}'s account suspended for expired subscription."})


@subscription_bp.route("/admin/notify-expiring", methods=["POST"])
@jwt_required()
def admin_notify_expiring():
    """
    Admin triggers renewal reminder notifications to all providers
    whose subscriptions expire within the next 7 days.
    Body: { days: 7 }  (optional, default 7)
    """
    admin, err = _admin_guard()
    if err:
        return err

    data = request.get_json(force=True) or {}
    days = int(data.get("days", 7))
    cutoff = datetime.utcnow() + timedelta(days=days)

    expiring_subs = (
        db.session.query(Subscription, User)
        .join(User, Subscription.user_id == User.id)
        .filter(
            Subscription.status.in_(["active", "grace"]),
            Subscription.expires_at <= cutoff,
            Subscription.expires_at >= datetime.utcnow(),
        )
        .all()
    )

    notified = 0
    for sub, user in expiring_subs:
        days_left = sub.days_remaining
        msg = (f"Reminder: Your Mech platform subscription expires in {days_left} day(s) "
               f"on {sub.expires_at.strftime('%d %b %Y')}. "
               f"Please renew to avoid service interruption.")
        _notify(user.id, msg, "subscription_renewal_reminder")
        try:
            send_sms(user.phone, msg)
        except Exception:
            pass
        notified += 1

    _log_action(admin.id, None, "notify_expiring",
                notes=f"Sent renewal reminders to {notified} providers expiring within {days} days")
    db.session.commit()

    return success_response({
        "message": f"Renewal reminders sent to {notified} provider(s).",
        "notified_count": notified,
    })


@subscription_bp.route("/admin/stats", methods=["GET"])
@jwt_required()
def admin_subscription_stats():
    """Summary stats for the subscriptions dashboard section."""
    admin, err = _admin_guard()
    if err:
        return err

    now = datetime.utcnow()
    soon = now + timedelta(days=7)

    active    = Subscription.query.filter_by(status="active").filter(Subscription.expires_at > now).count()
    grace     = Subscription.query.filter_by(status="grace").filter(Subscription.grace_until > now).count()
    pending   = Subscription.query.filter_by(status="pending_verification").count()
    unpaid    = Subscription.query.filter_by(status="unpaid").count()
    expired   = Subscription.query.filter(Subscription.status.in_(["expired", "suspended"])).count()
    expiring_7d = Subscription.query.filter(
        Subscription.status == "active",
        Subscription.expires_at <= soon,
        Subscription.expires_at >= now,
    ).count()

    return success_response({
        "active": active,
        "grace": grace,
        "pending_verification": pending,
        "unpaid": unpaid,
        "expired_or_suspended": expired,
        "expiring_within_7_days": expiring_7d,
    })
