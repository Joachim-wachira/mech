"""
Mech Platform — Main API Routes Blueprint
Handles: Profile, Nearby, Jobs, Reviews, Notifications, Dashboard
"""
import json
from datetime import datetime
from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from marshmallow import ValidationError

from app import db
from app.models import (
    User, JobRequest, Review, Notification,
    CallLog, IssueReport, Conversation, ConversationParticipant, Message
)
from app.schemas import (
    JobRequestSchema, ReviewSchema, AvailabilitySchema, IssueReportSchema
)
from app.utils import (
    success_response, error_response, nearby_providers,
    role_required, current_user, paginate_query
)

routes_bp = Blueprint("routes", __name__)


# ── Profile ──────────────────────────────────────────────────────
@routes_bp.route("/profile", methods=["GET"])
@jwt_required()
def get_profile():
    user = current_user()
    if not user:
        return error_response("User not found", 404)
    return success_response({"user": user.to_dict()})


@routes_bp.route("/profile", methods=["PUT"])
@jwt_required()
def update_profile():
    user = current_user()
    if not user:
        return error_response("User not found", 404)

    data = request.get_json(force=True) or {}
    allowed = ["full_name", "business_name", "location_text", "location_lat", "location_lng"]
    for field in allowed:
        if field in data:
            setattr(user, field, data[field])
    user.updated_at = datetime.utcnow()
    db.session.commit()
    return success_response({"user": user.to_dict(), "message": "Profile updated"})


@routes_bp.route("/profile/availability", methods=["PUT"])
@jwt_required()
def update_availability():
    schema = AvailabilitySchema()
    try:
        data = schema.load(request.get_json(force=True) or {})
    except ValidationError as e:
        return error_response(str(e.messages))

    user = current_user()
    if not user:
        return error_response("User not found", 404)

    user.is_available = data["available"]
    db.session.commit()
    return success_response({"available": user.is_available, "message": "Availability updated"})


# ── Nearby Providers ─────────────────────────────────────────────
@routes_bp.route("/nearby/<role>", methods=["GET"])
@jwt_required()
def get_nearby(role):
    if role not in ("mechanic", "spareshop", "rescue"):
        return error_response("Invalid role", 400)

    try:
        lat = float(request.args.get("lat", 0))
        lng = float(request.args.get("lng", 0))
    except (TypeError, ValueError):
        return error_response("Invalid coordinates", 400)

    providers = nearby_providers(role, lat, lng)
    return success_response({"providers": providers})


# ── Jobs ─────────────────────────────────────────────────────────
@routes_bp.route("/jobs", methods=["POST"])
@jwt_required()
def create_job():
    user = current_user()
    if not user or user.role != "driver":
        return error_response("Only drivers can create jobs", 403)

    schema = JobRequestSchema()
    try:
        data = schema.load(request.get_json(force=True) or {})
    except ValidationError as e:
        return error_response(str(e.messages))

    job = JobRequest(
        driver_id=user.id,
        provider_id=data["provider_id"],
        job_type=data["job_type"],
        vehicle_type=data.get("vehicle_type", ""),
        fault_description=data.get("fault_description", ""),
        driver_lat=data.get("driver_lat"),
        driver_lng=data.get("driver_lng"),
    )
    db.session.add(job)
    db.session.commit()

    # Notify provider
    notif = Notification(
        user_id=data["provider_id"],
        message=f"New job request from {user.full_name}",
        notification_type="job_request",
    )
    db.session.add(notif)
    db.session.commit()

    # Emit WS event
    from app import socketio
    socketio.emit(
        "job_request",
        {
            "job_id": job.id,
            "customer_name": user.full_name,
            "job_type": job.job_type,
        },
        room=f"user_{data['provider_id']}",
    )

    return success_response({"job_id": job.id, "message": "Job request sent"}, status=201)


@routes_bp.route("/jobs/<int:job_id>/accept", methods=["POST"])
@jwt_required()
def accept_job(job_id):
    user = current_user()
    job = JobRequest.query.get_or_404(job_id)
    if job.provider_id != user.id:
        return error_response("Not authorized", 403)

    job.status = "accepted"
    job.updated_at = datetime.utcnow()
    db.session.commit()

    notif = Notification(user_id=job.driver_id, message=f"Your job request was accepted by {user.full_name}", notification_type="job_update")
    db.session.add(notif)
    db.session.commit()

    from app import socketio
    socketio.emit("job_update", {"job_id": job.id, "status": "accepted"}, room=f"user_{job.driver_id}")

    return success_response({"message": "Job accepted"})


@routes_bp.route("/jobs/<int:job_id>/decline", methods=["POST"])
@jwt_required()
def decline_job(job_id):
    user = current_user()
    job = JobRequest.query.get_or_404(job_id)
    if job.provider_id != user.id:
        return error_response("Not authorized", 403)

    job.status = "declined"
    job.updated_at = datetime.utcnow()
    db.session.commit()

    return success_response({"message": "Job declined"})


@routes_bp.route("/jobs", methods=["GET"])
@jwt_required()
def list_jobs():
    user = current_user()
    page = int(request.args.get("page", 1))

    if user.role == "driver":
        q = JobRequest.query.filter_by(driver_id=user.id)
    else:
        q = JobRequest.query.filter_by(provider_id=user.id)

    q = q.order_by(JobRequest.created_at.desc())
    result = paginate_query(q, page)
    jobs = [
        {
            "id": j.id,
            "job_type": j.job_type,
            "status": j.status,
            "vehicle_type": j.vehicle_type,
            "fault_description": j.fault_description,
            "created_at": j.created_at.isoformat(),
        }
        for j in result["items"]
    ]
    return success_response({"jobs": jobs, "total": result["total"], "page": page})


# ── Orders (Spare shop) ──────────────────────────────────────────
@routes_bp.route("/orders/<int:order_id>/confirm", methods=["POST"])
@jwt_required()
def confirm_order(order_id):
    user = current_user()
    job = JobRequest.query.get_or_404(order_id)
    if job.provider_id != user.id:
        return error_response("Not authorized", 403)

    job.status = "accepted"
    job.updated_at = datetime.utcnow()
    db.session.commit()

    notif = Notification(user_id=job.driver_id, message=f"Your spare order was confirmed by {user.full_name}", notification_type="order_update")
    db.session.add(notif)
    db.session.commit()

    return success_response({"message": "Order confirmed"})


# ── Reviews ──────────────────────────────────────────────────────
@routes_bp.route("/reviews", methods=["POST"])
@jwt_required()
def submit_review():
    user = current_user()
    schema = ReviewSchema()
    try:
        data = schema.load(request.get_json(force=True) or {})
    except ValidationError as e:
        return error_response(str(e.messages))

    review = Review(
        reviewer_id=user.id,
        reviewee_id=data["reviewee_id"],
        job_id=data.get("job_id"),
        rating=data["rating"],
        comment=data.get("comment", ""),
    )
    db.session.add(review)

    # Update reviewee's average rating
    reviewee = User.query.get(data["reviewee_id"])
    if reviewee:
        all_reviews = Review.query.filter_by(reviewee_id=reviewee.id).all()
        reviewee.rating_count = len(all_reviews) + 1
        total = sum(r.rating for r in all_reviews) + data["rating"]
        reviewee.rating_avg = round(total / reviewee.rating_count, 1)

    db.session.commit()
    return success_response({"message": "Review submitted"}, status=201)


@routes_bp.route("/reviews/<int:user_id>", methods=["GET"])
def get_reviews(user_id):
    page = int(request.args.get("page", 1))
    q = Review.query.filter_by(reviewee_id=user_id).order_by(Review.created_at.desc())
    result = paginate_query(q, page)
    reviews = [
        {
            "id": r.id,
            "reviewer_name": r.reviewer.full_name if r.reviewer else "Anonymous",
            "rating": r.rating,
            "comment": r.comment,
            "created_at": r.created_at.isoformat(),
        }
        for r in result["items"]
    ]
    return success_response({"reviews": reviews, "total": result["total"]})


# ── Issues ───────────────────────────────────────────────────────
@routes_bp.route("/issues", methods=["POST"])
@jwt_required()
def report_issue():
    user = current_user()
    schema = IssueReportSchema()
    try:
        data = schema.load(request.get_json(force=True) or {})
    except ValidationError as e:
        return error_response(str(e.messages))

    issue = IssueReport(user_id=user.id, description=data["description"])
    db.session.add(issue)
    db.session.commit()
    return success_response({"issue_id": issue.id, "message": "Issue reported"}, status=201)


# ── Notifications ────────────────────────────────────────────────
@routes_bp.route("/notifications", methods=["GET"])
@jwt_required()
def get_notifications():
    user = current_user()
    page = int(request.args.get("page", 1))
    q = Notification.query.filter_by(user_id=user.id).order_by(Notification.created_at.desc())
    result = paginate_query(q, page)
    notifs = [
        {"id": n.id, "message": n.message, "type": n.notification_type, "read": n.is_read, "created_at": n.created_at.isoformat()}
        for n in result["items"]
    ]
    return success_response({"notifications": notifs, "total": result["total"]})


@routes_bp.route("/notifications/read", methods=["POST"])
@jwt_required()
def mark_notifications_read():
    user = current_user()
    Notification.query.filter_by(user_id=user.id, is_read=False).update({"is_read": True})
    db.session.commit()
    return success_response({"message": "All notifications marked as read"})


# ── Conversations ────────────────────────────────────────────────
@routes_bp.route("/conversations", methods=["GET"])
@jwt_required()
def list_conversations():
    user = current_user()
    participant_records = ConversationParticipant.query.filter_by(user_id=user.id).all()
    conv_ids = [p.conversation_id for p in participant_records]
    convs = Conversation.query.filter(Conversation.id.in_(conv_ids)).order_by(Conversation.updated_at.desc()).all()

    results = []
    for c in convs:
        last_msg = c.messages.order_by(Message.created_at.desc()).first()
        unread = c.messages.filter_by(is_read=False).filter(Message.sender_id != user.id).count()
        d = c.to_dict()
        d["last_message"] = last_msg.content if last_msg else ""
        d["unread"] = unread
        results.append(d)

    return success_response({"conversations": results})


@routes_bp.route("/conversations/<int:conv_id>/messages", methods=["GET"])
@jwt_required()
def get_messages(conv_id):
    page = int(request.args.get("page", 1))
    q = Message.query.filter_by(conversation_id=conv_id).order_by(Message.created_at.asc())
    result = paginate_query(q, page, per_page=50)
    msgs = [m.to_dict() for m in result["items"]]
    return success_response({"messages": msgs, "total": result["total"]})


# ── Call Logs ────────────────────────────────────────────────────
@routes_bp.route("/calls", methods=["GET"])
@jwt_required()
def get_call_logs():
    user = current_user()
    page = int(request.args.get("page", 1))
    q = CallLog.query.filter(
        (CallLog.caller_id == user.id) | (CallLog.callee_id == user.id)
    ).order_by(CallLog.created_at.desc())
    result = paginate_query(q, page)
    calls = [c.to_dict() for c in result["items"]]
    return success_response({"calls": calls, "total": result["total"]})


# ── Dashboard ping (lightweight poll) ───────────────────────────
@routes_bp.route("/dashboard/ping", methods=["GET"])
@jwt_required()
def dashboard_ping():
    user = current_user()
    if not user:
        return error_response("Not found", 404)

    unread_notifs = Notification.query.filter_by(user_id=user.id, is_read=False).all()
    notifications = [n.message for n in unread_notifs[:5]]

    return success_response({
        "notifications": notifications,
        "is_available": user.is_available,
        "last_seen": user.last_seen.isoformat() if user.last_seen else None,
    })


# ── Emergency Rescue ─────────────────────────────────────────────
@routes_bp.route("/emergency", methods=["POST"])
@jwt_required()
def emergency_rescue():
    user = current_user()
    data = request.get_json(force=True) or {}

    # Log a call entry
    call = CallLog(
        caller_id=user.id,
        call_type="emergency",
        status="initiated",
    )
    db.session.add(call)

    # Notify all available rescue/admin users
    admins = User.query.filter_by(role="admin", is_active=True).all()
    for admin in admins:
        notif = Notification(
            user_id=admin.id,
            message=f"EMERGENCY: {user.full_name} needs rescue at {data.get('location', 'unknown location')}",
            notification_type="emergency",
        )
        db.session.add(notif)

    db.session.commit()

    from app import socketio
    socketio.emit("emergency_alert", {"user_id": user.id, "user_name": user.full_name, "location": data.get("location")}, broadcast=True)

    return success_response({"message": "Emergency rescue request sent"}, status=201)


# ── Start or get conversation between two users ──────────────────
@routes_bp.route("/conversations/start", methods=["POST"])
@jwt_required()
def start_conversation():
    from app.models import Conversation, ConversationParticipant
    user = current_user()
    data = request.get_json(silent=True) or {}
    other_id = data.get("participant_id")
    if not other_id:
        return error_response("participant_id required", 400)
    other = User.query.get(other_id)
    if not other:
        return error_response("User not found", 404)

    # Find existing conversation between these two users
    my_convs = {p.conversation_id for p in ConversationParticipant.query.filter_by(user_id=user.id).all()}
    their_convs = {p.conversation_id for p in ConversationParticipant.query.filter_by(user_id=other_id).all()}
    shared = my_convs & their_convs
    if shared:
        conv_id = sorted(shared)[0]
        return success_response({"conversation_id": conv_id, "created": False})

    # Create new conversation
    conv = Conversation()
    db.session.add(conv)
    db.session.flush()
    for uid in [user.id, other_id]:
        db.session.add(ConversationParticipant(conversation_id=conv.id, user_id=uid))
    try:
        db.session.commit()
        return success_response({"conversation_id": conv.id, "created": True}, status=201)
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error(f"[start_conversation] {exc}")
        return error_response("Could not create conversation", 500)


# ── Mechanic stats ───────────────────────────────────────────────
@routes_bp.route("/mechanic/stats", methods=["GET"])
@jwt_required()
def mechanic_stats():
    from app.models import JobRequest
    user = current_user()
    if not user or user.role != "mechanic":
        return error_response("Mechanic access only", 403)
    incoming = JobRequest.query.filter_by(provider_id=user.id, status="pending").count()
    active   = JobRequest.query.filter_by(provider_id=user.id, status="active").count()
    earnings = db.session.query(db.func.sum(JobRequest.amount_kes)).filter_by(provider_id=user.id, status="completed").scalar() or 0
    return success_response({
        "incoming_jobs":   incoming,
        "active_repairs":  active,
        "total_earnings":  float(earnings),
    })


# ── Incoming job requests for mechanic ──────────────────────────
@routes_bp.route("/jobs/incoming", methods=["GET"])
@jwt_required()
def incoming_jobs():
    from app.models import JobRequest
    user = current_user()
    if not user or user.role != "mechanic":
        return error_response("Mechanic access only", 403)
    jobs = JobRequest.query.filter_by(provider_id=user.id, status="pending").order_by(JobRequest.created_at.desc()).limit(20).all()
    result = []
    for j in jobs:
        d = j.to_dict()
        driver = User.query.get(j.driver_id)
        d["driver_name"] = driver.full_name if driver else "Driver"
        result.append(d)
    return success_response({"jobs": result})


# ── Spare shop stats ─────────────────────────────────────────────
@routes_bp.route("/spareshop/stats", methods=["GET"])
@jwt_required()
def spareshop_stats():
    from app.models import JobRequest
    user = current_user()
    if not user or user.role != "spareshop":
        return error_response("Spare shop access only", 403)
    requested = JobRequest.query.filter_by(provider_id=user.id).count()
    earnings  = db.session.query(db.func.sum(JobRequest.amount_kes)).filter_by(provider_id=user.id, status="completed").scalar() or 0
    return success_response({
        "spares_requested": requested,
        "total_earnings":   float(earnings),
    })


# ── Incoming orders for spare shop ──────────────────────────────
@routes_bp.route("/orders/incoming", methods=["GET"])
@jwt_required()
def incoming_orders():
    from app.models import JobRequest
    user = current_user()
    if not user or user.role != "spareshop":
        return error_response("Spare shop access only", 403)
    orders = JobRequest.query.filter_by(provider_id=user.id, status="pending").order_by(JobRequest.created_at.desc()).limit(20).all()
    result = []
    for o in orders:
        d = o.to_dict()
        customer = User.query.get(o.driver_id)
        d["customer_name"] = customer.full_name if customer else "Customer"
        d["customer_id"]   = o.driver_id
        d["part_name"]     = o.fault_description or "Spare Part"
        result.append(d)
    return success_response({"orders": result})

