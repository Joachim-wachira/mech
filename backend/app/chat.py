"""
Mech Platform — WebSocket Event Handlers (Flask-SocketIO)
Handles: real-time messages, presence, calls, notifications
"""
from datetime import datetime
from flask import request
from flask_socketio import emit, join_room, leave_room, disconnect
from flask_jwt_extended import decode_token
from jwt.exceptions import DecodeError, ExpiredSignatureError

from app import socketio, db
from app.models import (
    User, Message, Conversation, ConversationParticipant,
    CallLog, Notification
)

# Track online users: { user_id: sid }
_online_users = {}

# Utility map for sid→token (populated during auth if needed)
_sid_to_token = {}


def _get_user_from_token(token):
    """Decode JWT and return User or None."""
    try:
        decoded = decode_token(token)
        user_id = decoded.get("sub")
        return User.query.get(user_id)
    except (DecodeError, ExpiredSignatureError, Exception):
        return None


# ── Connection ───────────────────────────────────────────────────
@socketio.on("connect")
def on_connect(auth):
    token = (auth or {}).get("token") or request.args.get("token")
    if not token:
        disconnect()
        return False

    user = _get_user_from_token(token)
    if not user or not user.is_active:
        disconnect()
        return False

    # Join personal room
    join_room(f"user_{user.id}")
    _online_users[user.id] = request.sid

    # Update last seen
    user.last_seen = datetime.utcnow()
    db.session.commit()

    # Broadcast presence to all
    emit("user_status", {"user_id": user.id, "online": True}, broadcast=True)
    return True


@socketio.on("disconnect")
def on_disconnect():
    # Find which user this sid belongs to
    user_id = next((uid for uid, sid in _online_users.items() if sid == request.sid), None)
    if user_id:
        _online_users.pop(user_id, None)
        user = User.query.get(user_id)
        if user:
            user.last_seen = datetime.utcnow()
            db.session.commit()
        emit("user_status", {"user_id": user_id, "online": False}, broadcast=True)


# ── Explicit online announcement ─────────────────────────────────
@socketio.on("user_online")
def on_user_online(data):
    pass  # handled in connect; kept for legacy clients


# ── Send Message ─────────────────────────────────────────────────
@socketio.on("send_message")
def on_send_message(data):
    token = (request.environ.get("HTTP_AUTHORIZATION") or "").replace("Bearer ", "")
    if not token:
        token = _sid_to_token.get(request.sid, "")

    # Minimal validation
    conversation_id = data.get("conversation_id")
    content = data.get("message") or data.get("content", "")
    msg_type = data.get("type", "text")

    if not conversation_id or not content:
        return

    conv = Conversation.query.get(conversation_id)
    if not conv:
        return

    # Find sender user via sid
    sender_id = next((uid for uid, sid in _online_users.items() if sid == request.sid), None)
    if not sender_id:
        return

    msg = Message(
        conversation_id=conversation_id,
        sender_id=sender_id,
        content=content,
        message_type=msg_type,
    )
    db.session.add(msg)

    # Update conversation timestamp
    conv.updated_at = datetime.utcnow()
    db.session.commit()

    sender = User.query.get(sender_id)
    payload = {
        "id": msg.id,
        "conversation_id": conversation_id,
        "sender_id": sender_id,
        "sender_name": sender.full_name if sender else "Unknown",
        "message": content,
        "message_type": msg_type,
        "created_at": msg.created_at.isoformat(),
    }

    # Deliver to all participants
    participants = ConversationParticipant.query.filter_by(conversation_id=conversation_id).all()
    for p in participants:
        emit("new_message", payload, room=f"user_{p.user_id}")


# ── Typing indicators ────────────────────────────────────────────
@socketio.on("typing")
def on_typing(data):
    sender_id = next((uid for uid, sid in _online_users.items() if sid == request.sid), None)
    conversation_id = data.get("conversation_id")
    if not sender_id or not conversation_id:
        return

    participants = ConversationParticipant.query.filter_by(conversation_id=conversation_id).all()
    for p in participants:
        if p.user_id != sender_id:
            emit("typing", {"user_id": sender_id, "conversation_id": conversation_id}, room=f"user_{p.user_id}")


@socketio.on("stop_typing")
def on_stop_typing(data):
    sender_id = next((uid for uid, sid in _online_users.items() if sid == request.sid), None)
    conversation_id = data.get("conversation_id")
    if not sender_id or not conversation_id:
        return

    participants = ConversationParticipant.query.filter_by(conversation_id=conversation_id).all()
    for p in participants:
        if p.user_id != sender_id:
            emit("stop_typing", {"user_id": sender_id}, room=f"user_{p.user_id}")


# ── Call Initiation ──────────────────────────────────────────────
@socketio.on("initiate_call")
def on_initiate_call(data):
    caller_id = next((uid for uid, sid in _online_users.items() if sid == request.sid), None)
    target_id = data.get("target_user_id")

    if not caller_id or not target_id:
        return

    caller = User.query.get(caller_id)
    call_log = CallLog(
        caller_id=caller_id,
        callee_id=target_id,
        call_type="voice",
        status="initiated",
    )
    db.session.add(call_log)
    db.session.commit()

    emit(
        "incoming_call",
        {
            "call_id": call_log.id,
            "caller_id": caller_id,
            "caller_name": caller.full_name if caller else "Unknown",
        },
        room=f"user_{target_id}",
    )


@socketio.on("call_answered")
def on_call_answered(data):
    call_id = data.get("call_id")
    call = CallLog.query.get(call_id)
    if call:
        call.status = "answered"
        db.session.commit()
        emit("call_answered", {"call_id": call_id}, room=f"user_{call.caller_id}")


@socketio.on("call_ended")
def on_call_ended(data):
    call_id = data.get("call_id")
    duration = data.get("duration_seconds", 0)
    call = CallLog.query.get(call_id)
    if call:
        call.status = "ended"
        call.duration_seconds = duration
        call.ended_at = datetime.utcnow()
        db.session.commit()


@socketio.on("call_missed")
def on_call_missed(data):
    call_id = data.get("call_id")
    call = CallLog.query.get(call_id)
    if call:
        call.status = "missed"
        db.session.commit()
        emit("call_missed", {"call_id": call_id}, room=f"user_{call.caller_id}")


# ── Emergency ────────────────────────────────────────────────────
@socketio.on("emergency_rescue")
def on_emergency_rescue(data):
    caller_id = next((uid for uid, sid in _online_users.items() if sid == request.sid), None)
    if not caller_id:
        return

    user = User.query.get(caller_id)
    call_log = CallLog(
        caller_id=caller_id,
        call_type="emergency",
        status="initiated",
    )
    db.session.add(call_log)

    # Notify admins
    admins = User.query.filter_by(role="admin", is_active=True).all()
    for admin in admins:
        notif = Notification(
            user_id=admin.id,
            message=f"EMERGENCY from {user.full_name if user else caller_id}",
            notification_type="emergency",
        )
        db.session.add(notif)
        emit("emergency_alert", {
            "user_id": caller_id,
            "user_name": user.full_name if user else "Unknown",
            "location": data.get("location"),
        }, room=f"user_{admin.id}")

    db.session.commit()


# ── Availability Update ──────────────────────────────────────────
@socketio.on("availability_change")
def on_availability_change(data):
    user_id = data.get("user_id")
    available = data.get("available", True)
    emit("provider_availability", {"user_id": user_id, "available": available}, broadcast=True)


# ── Join/Leave conversation room ─────────────────────────────────
@socketio.on("join_conversation")
def on_join_conversation(data):
    conv_id = data.get("conversation_id")
    if conv_id:
        join_room(f"conv_{conv_id}")


@socketio.on("leave_conversation")
def on_leave_conversation(data):
    conv_id = data.get("conversation_id")
    if conv_id:
        leave_room(f"conv_{conv_id}")


# ── Read receipt ─────────────────────────────────────────────────
@socketio.on("mark_read")
def on_mark_read(data):
    sender_id = next((uid for uid, sid in _online_users.items() if sid == request.sid), None)
    conv_id = data.get("conversation_id")
    if not sender_id or not conv_id:
        return

    Message.query.filter(
        Message.conversation_id == conv_id,
        Message.sender_id != sender_id,
        Message.is_read == False,
    ).update({"is_read": True})
    db.session.commit()

    emit("messages_read", {"conversation_id": conv_id, "reader_id": sender_id}, room=f"conv_{conv_id}")
