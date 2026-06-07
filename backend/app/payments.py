"""
Mech Platform — Payments Blueprint (KES / M-Pesa stub)
Defines transaction routes and financial record management.
All amounts are in Kenyan Shillings (KES).
"""
import uuid
from datetime import datetime
from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from app import db
from app.models import Transaction, User, JobRequest, Notification
from app.utils import (
    success_response, error_response, current_user,
    paginate_query, format_kes
)

payments_bp = Blueprint("payments", __name__)


def _generate_reference():
    """Generate a unique transaction reference."""
    return f"MECH-{uuid.uuid4().hex[:10].upper()}"


# ── Initiate Payment ──────────────────────────────────────────────
@payments_bp.route("/initiate", methods=["POST"])
@jwt_required()
def initiate_payment():
    """
    Initiate a KES payment from payer to payee for a job.
    In production this would call the M-Pesa STK Push API.
    """
    payer = current_user()
    if not payer:
        return error_response("Authentication required", 401)

    data = request.get_json(force=True) or {}
    payee_id = data.get("payee_id")
    job_id = data.get("job_id")
    amount_kes = data.get("amount_kes")

    if not payee_id or not amount_kes:
        return error_response("payee_id and amount_kes are required")

    try:
        amount_kes = float(amount_kes)
        if amount_kes <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return error_response("Invalid amount")

    payee = User.query.get(payee_id)
    if not payee:
        return error_response("Payee not found", 404)

    reference = _generate_reference()

    txn = Transaction(
        payer_id=payer.id,
        payee_id=payee_id,
        job_id=job_id,
        amount_kes=amount_kes,
        currency="KES",
        status="pending",
        payment_method="mpesa",
        reference=reference,
    )
    db.session.add(txn)
    db.session.commit()

    # In production: call M-Pesa STK Push here using payer.phone
    # For now, auto-complete in stub mode
    txn.status = "completed"
    txn.completed_at = datetime.utcnow()
    db.session.commit()

    # Update provider earnings
    if payee.role == "mechanic" and payee.mechanic_profile:
        payee.mechanic_profile.total_earnings += amount_kes
    elif payee.role == "spareshop" and payee.shop_profile:
        payee.shop_profile.total_earnings += amount_kes

    # Notify payee
    notif = Notification(
        user_id=payee_id,
        message=f"Payment received: {format_kes(amount_kes)} from {payer.full_name}",
        notification_type="payment",
    )
    db.session.add(notif)
    db.session.commit()

    from app import socketio
    socketio.emit(
        "notification",
        {"message": notif.message},
        room=f"user_{payee_id}",
    )

    return success_response(
        {
            "transaction_id": txn.id,
            "reference": reference,
            "amount_kes": amount_kes,
            "amount_formatted": format_kes(amount_kes),
            "status": txn.status,
            "message": "Payment processed successfully",
        },
        status=201,
    )


# ── Transaction History ───────────────────────────────────────────
@payments_bp.route("/history", methods=["GET"])
@jwt_required()
def payment_history():
    user = current_user()
    if not user:
        return error_response("Authentication required", 401)

    page = int(request.args.get("page", 1))
    direction = request.args.get("direction", "all")  # sent | received | all

    q = Transaction.query
    if direction == "sent":
        q = q.filter_by(payer_id=user.id)
    elif direction == "received":
        q = q.filter_by(payee_id=user.id)
    else:
        q = q.filter(
            (Transaction.payer_id == user.id) | (Transaction.payee_id == user.id)
        )

    q = q.order_by(Transaction.created_at.desc())
    result = paginate_query(q, page)

    txns = [t.to_dict() for t in result["items"]]
    return success_response({"transactions": txns, "total": result["total"], "page": page})


# ── Transaction Detail ────────────────────────────────────────────
@payments_bp.route("/<int:txn_id>", methods=["GET"])
@jwt_required()
def get_transaction(txn_id):
    user = current_user()
    txn = Transaction.query.get_or_404(txn_id)

    if txn.payer_id != user.id and txn.payee_id != user.id and user.role != "admin":
        return error_response("Access denied", 403)

    return success_response({"transaction": txn.to_dict()})


# ── Earnings Summary ──────────────────────────────────────────────
@payments_bp.route("/earnings", methods=["GET"])
@jwt_required()
def earnings_summary():
    user = current_user()
    if not user or user.role not in ("mechanic", "spareshop"):
        return error_response("Access denied", 403)

    total = (
        db.session.query(db.func.sum(Transaction.amount_kes))
        .filter_by(payee_id=user.id, status="completed")
        .scalar()
        or 0.0
    )

    # This week
    from datetime import timedelta
    week_start = datetime.utcnow() - timedelta(days=7)
    this_week = (
        db.session.query(db.func.sum(Transaction.amount_kes))
        .filter(
            Transaction.payee_id == user.id,
            Transaction.status == "completed",
            Transaction.completed_at >= week_start,
        )
        .scalar()
        or 0.0
    )

    return success_response({
        "total_earnings_kes": total,
        "total_formatted": format_kes(total),
        "this_week_kes": this_week,
        "this_week_formatted": format_kes(this_week),
        "currency": "KES",
    })


# ── Refund (admin only) ───────────────────────────────────────────
@payments_bp.route("/<int:txn_id>/refund", methods=["POST"])
@jwt_required()
def refund_transaction(txn_id):
    admin = current_user()
    if not admin or admin.role != "admin":
        return error_response("Admin access required", 403)

    txn = Transaction.query.get_or_404(txn_id)
    if txn.status != "completed":
        return error_response("Only completed transactions can be refunded")

    txn.status = "refunded"
    db.session.commit()

    # Reverse provider earnings
    payee = User.query.get(txn.payee_id)
    if payee and payee.role == "mechanic" and payee.mechanic_profile:
        payee.mechanic_profile.total_earnings -= txn.amount_kes
    elif payee and payee.role == "spareshop" and payee.shop_profile:
        payee.shop_profile.total_earnings -= txn.amount_kes

    # Notify payer
    notif = Notification(
        user_id=txn.payer_id,
        message=f"Refund processed: {format_kes(txn.amount_kes)} — Ref: {txn.reference}",
        notification_type="payment",
    )
    db.session.add(notif)
    db.session.commit()

    return success_response({"message": "Transaction refunded", "reference": txn.reference})


# ── Admin: All Transactions ───────────────────────────────────────
@payments_bp.route("/admin/all", methods=["GET"])
@jwt_required()
def admin_all_transactions():
    admin = current_user()
    if not admin or admin.role != "admin":
        return error_response("Admin access required", 403)

    page = int(request.args.get("page", 1))
    status = request.args.get("status")
    q = Transaction.query
    if status:
        q = q.filter_by(status=status)
    q = q.order_by(Transaction.created_at.desc())
    result = paginate_query(q, page)
    txns = [t.to_dict() for t in result["items"]]

    total_volume = (
        db.session.query(db.func.sum(Transaction.amount_kes))
        .filter_by(status="completed")
        .scalar()
        or 0.0
    )

    return success_response({
        "transactions": txns,
        "total": result["total"],
        "total_volume_kes": total_volume,
        "total_volume_formatted": format_kes(total_volume),
    })
