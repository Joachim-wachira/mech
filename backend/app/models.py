"""
Mech Platform — SQLAlchemy Database Models
"""
from datetime import datetime, timezone
from app import db
from werkzeug.security import generate_password_hash, check_password_hash


class User(db.Model):
    __tablename__ = "users"

    id              = db.Column(db.Integer, primary_key=True)
    full_name       = db.Column(db.String(120), nullable=False)
    email           = db.Column(db.String(180), unique=True, nullable=False, index=True)
    phone           = db.Column(db.String(30),  unique=True, nullable=False)
    password_hash   = db.Column(db.String(256), nullable=False)
    role            = db.Column(db.String(20),  nullable=False)  # driver|mechanic|spareshop|admin
    business_name   = db.Column(db.String(180))
    location_text   = db.Column(db.String(400))
    location_lat    = db.Column(db.Float)
    location_lng    = db.Column(db.Float)
    avatar_url      = db.Column(db.String(400))
    is_verified     = db.Column(db.Boolean, default=False)
    is_active       = db.Column(db.Boolean, default=True)
    is_suspended    = db.Column(db.Boolean, default=False)
    suspended_until = db.Column(db.DateTime)
    phone_verified  = db.Column(db.Boolean, default=False)
    is_available    = db.Column(db.Boolean, default=True)
    rating_avg      = db.Column(db.Float,   default=0.0)
    rating_count    = db.Column(db.Integer, default=0)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at      = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_seen       = db.Column(db.DateTime)

    # Relationships
    mechanic_profile = db.relationship(
        "MechanicProfile", backref="user", uselist=False, cascade="all,delete"
    )
    shop_profile = db.relationship(
        "SpareShopProfile", backref="user", uselist=False, cascade="all,delete"
    )
    sent_messages = db.relationship(
        "Message", foreign_keys="Message.sender_id", backref="sender", lazy="dynamic"
    )
    reviews_received = db.relationship(
        "Review", foreign_keys="Review.reviewee_id", backref="reviewee", lazy="dynamic"
    )
    reviews_given = db.relationship(
        "Review", foreign_keys="Review.reviewer_id", backref="reviewer", lazy="dynamic"
    )

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            "id":            self.id,
            "full_name":     self.full_name,
            "email":         self.email,
            "phone":         self.phone,
            "role":          self.role,
            "business_name": self.business_name,
            "location_text": self.location_text,
            "location_lat":  self.location_lat,
            "location_lng":  self.location_lng,
            "is_verified":   self.is_verified,
            "is_active":     self.is_active,
            "is_available":  self.is_available,
            "rating_avg":    self.rating_avg,
            "rating_count":  self.rating_count,
            "created_at":    self.created_at.isoformat() if self.created_at else None,
        }


class MechanicProfile(db.Model):
    __tablename__ = "mechanic_profiles"

    id             = db.Column(db.Integer, primary_key=True)
    user_id        = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    vehicle_brands = db.Column(db.Text)        # JSON array stored as text
    services       = db.Column(db.Text)        # JSON array stored as text
    id_doc_url     = db.Column(db.String(400))
    cert_doc_url   = db.Column(db.String(400))
    total_earnings = db.Column(db.Float, default=0.0)
    active_repairs = db.Column(db.Integer, default=0)


class SpareShopProfile(db.Model):
    __tablename__ = "spare_shop_profiles"

    id                   = db.Column(db.Integer, primary_key=True)
    user_id              = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    inventory_categories = db.Column(db.Text)  # JSON array
    delivery_options     = db.Column(db.Text)  # JSON array
    delivery_km          = db.Column(db.Float)
    id_doc_url           = db.Column(db.String(400))
    cert_doc_url         = db.Column(db.String(400))
    total_earnings       = db.Column(db.Float, default=0.0)
    pending_deliveries   = db.Column(db.Integer, default=0)


class Conversation(db.Model):
    __tablename__ = "conversations"

    id         = db.Column(db.Integer, primary_key=True)
    is_group   = db.Column(db.Boolean, default=False)
    group_name = db.Column(db.String(180))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    participants = db.relationship(
        "ConversationParticipant", backref="conversation", cascade="all,delete"
    )
    messages = db.relationship(
        "Message", backref="conversation", lazy="dynamic", cascade="all,delete"
    )

    def to_dict(self):
        return {
            "id":         self.id,
            "is_group":   self.is_group,
            "group_name": self.group_name,
            "created_at": self.created_at.isoformat(),
        }


class ConversationParticipant(db.Model):
    __tablename__ = "conversation_participants"

    id              = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversations.id", ondelete="CASCADE"))
    user_id         = db.Column(db.Integer, db.ForeignKey("users.id",         ondelete="CASCADE"))
    joined_at       = db.Column(db.DateTime, default=datetime.utcnow)
    last_read_at    = db.Column(db.DateTime)


class Message(db.Model):
    __tablename__ = "messages"

    id              = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversations.id", ondelete="CASCADE"))
    sender_id       = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    message_type    = db.Column(db.String(20), default="text")  # text|image|voice|file
    content         = db.Column(db.Text)
    media_url       = db.Column(db.String(400))
    is_read         = db.Column(db.Boolean, default=False)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id":              self.id,
            "conversation_id": self.conversation_id,
            "sender_id":       self.sender_id,
            "sender_name":     self.sender.full_name if self.sender else "Unknown",
            "message_type":    self.message_type,
            "content":         self.content,
            "media_url":       self.media_url,
            "is_read":         self.is_read,
            "created_at":      self.created_at.isoformat(),
        }


class CallLog(db.Model):
    __tablename__ = "call_logs"

    id               = db.Column(db.Integer, primary_key=True)
    caller_id        = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    callee_id        = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    call_type        = db.Column(db.String(20), default="voice")     # voice|emergency
    status           = db.Column(db.String(20), default="initiated") # initiated|answered|missed|ended
    duration_seconds = db.Column(db.Integer, default=0)
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)
    ended_at         = db.Column(db.DateTime)

    caller = db.relationship("User", foreign_keys=[caller_id])
    callee = db.relationship("User", foreign_keys=[callee_id])

    def to_dict(self):
        return {
            "id":               self.id,
            "caller_id":        self.caller_id,
            "callee_id":        self.callee_id,
            "call_type":        self.call_type,
            "status":           self.status,
            "duration_seconds": self.duration_seconds,
            "created_at":       self.created_at.isoformat(),
        }


class JobRequest(db.Model):
    __tablename__ = "job_requests"

    id                = db.Column(db.Integer, primary_key=True)
    driver_id         = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    provider_id       = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    job_type          = db.Column(db.String(20))   # mechanic|spareshop|rescue
    vehicle_type      = db.Column(db.String(100))
    fault_description = db.Column(db.Text)
    status            = db.Column(db.String(20), default="pending")  # pending|accepted|declined|completed
    driver_lat        = db.Column(db.Float)
    driver_lng        = db.Column(db.Float)
    amount_kes        = db.Column(db.Float, default=0.0)
    created_at        = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at        = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    driver   = db.relationship("User", foreign_keys=[driver_id])
    provider = db.relationship("User", foreign_keys=[provider_id])


class Review(db.Model):
    __tablename__ = "reviews"

    id          = db.Column(db.Integer, primary_key=True)
    reviewer_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewee_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    job_id      = db.Column(db.Integer, db.ForeignKey("job_requests.id", ondelete="SET NULL"), nullable=True)
    rating      = db.Column(db.Integer, nullable=False)  # 1-5
    comment     = db.Column(db.Text)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)


class Notification(db.Model):
    __tablename__ = "notifications"

    id                = db.Column(db.Integer, primary_key=True)
    user_id           = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"))
    message           = db.Column(db.Text, nullable=False)
    notification_type = db.Column(db.String(40), default="general")
    is_read           = db.Column(db.Boolean, default=False)
    created_at        = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref=db.backref("notifications", lazy="dynamic"))


class SmsVerification(db.Model):
    __tablename__ = "sms_verifications"

    id         = db.Column(db.Integer, primary_key=True)
    phone      = db.Column(db.String(30), nullable=False, index=True)
    code       = db.Column(db.String(10), nullable=False)
    is_used    = db.Column(db.Boolean, default=False)
    expires_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Transaction(db.Model):
    """Financial transaction record (KES)."""
    __tablename__ = "transactions"

    id             = db.Column(db.Integer, primary_key=True)
    payer_id       = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    payee_id       = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    job_id         = db.Column(db.Integer, db.ForeignKey("job_requests.id", ondelete="SET NULL"), nullable=True)
    amount_kes     = db.Column(db.Float, nullable=False)
    currency       = db.Column(db.String(5),  default="KES")
    status         = db.Column(db.String(20), default="pending")  # pending|completed|failed|refunded
    payment_method = db.Column(db.String(40), default="mpesa")
    reference      = db.Column(db.String(100), unique=True)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at   = db.Column(db.DateTime)

    payer = db.relationship("User", foreign_keys=[payer_id])
    payee = db.relationship("User", foreign_keys=[payee_id])

    def to_dict(self):
        return {
            "id":             self.id,
            "payer_id":       self.payer_id,
            "payee_id":       self.payee_id,
            "amount_kes":     self.amount_kes,
            "currency":       self.currency,
            "status":         self.status,
            "payment_method": self.payment_method,
            "reference":      self.reference,
            "created_at":     self.created_at.isoformat(),
        }


class IssueReport(db.Model):
    __tablename__ = "issue_reports"

    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    description = db.Column(db.Text, nullable=False)
    status      = db.Column(db.String(20), default="open")  # open|resolved|closed
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref=db.backref("issues", lazy="dynamic"))


class AdminAction(db.Model):
    __tablename__ = "admin_actions"

    id             = db.Column(db.Integer, primary_key=True)
    admin_id       = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    target_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action         = db.Column(db.String(50), nullable=False)  # suspend|deactivate|verify|update_profile
    notes          = db.Column(db.Text)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)

    admin  = db.relationship("User", foreign_keys=[admin_id])
    target = db.relationship("User", foreign_keys=[target_user_id])


# ── Rating ────────────────────────────────────────────────────────
# Stores driver-submitted ratings for mechanics and spare shops.
# Rules enforced in ratings_routes.py:
#   - Only drivers submit ratings (reviewer must have role='driver')
#   - Mechanics/spare shops can only READ their own ratings
#   - Only admins can edit or delete ratings
class Rating(db.Model):
    __tablename__ = "ratings"

    id            = db.Column(db.Integer, primary_key=True)

    # Who submitted the rating — must be a driver (enforced in route)
    reviewer_id   = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewer_name = db.Column(db.String(120), nullable=False)

    # Who is being rated — mechanic or spareshop
    target_id     = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    target_role   = db.Column(db.String(20), nullable=False)   # 'mechanic' | 'spareshop'

    # Rating content
    stars         = db.Column(db.Integer, nullable=False)      # 1–5
    comment       = db.Column(db.Text, default="")

    # Timestamps
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at    = db.Column(db.DateTime, nullable=True)

    # Admin audit trail — tracks which admin last modified the rating
    modified_by   = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # One driver can rate each target only once (upsert behaviour)
    __table_args__ = (
        db.UniqueConstraint("reviewer_id", "target_id", name="uq_reviewer_target"),
    )

    reviewer  = db.relationship("User", foreign_keys=[reviewer_id])
    target    = db.relationship("User", foreign_keys=[target_id])
    modifier  = db.relationship("User", foreign_keys=[modified_by])

    def __repr__(self):
        return f"<Rating {self.stars}★ by user {self.reviewer_id} → user {self.target_id}>"


# ── EmergencyCallLog ──────────────────────────────────────────────
# Records every time a user taps to call an emergency service.
# Written by emergency_routes.py → POST /api/emergency/log
# Visible in the History tab of chat.html (emergency calls section).
class EmergencyCallLog(db.Model):
    __tablename__ = "emergency_call_logs"

    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    service_name = db.Column(db.String(200), nullable=False)
    contact      = db.Column(db.String(50),  nullable=False)
    called_at    = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref=db.backref("emergency_calls", lazy="dynamic"))

    def __repr__(self):
        return f"<EmergencyCallLog user={self.user_id} → {self.service_name}>"

    def to_dict(self):
        return {
            "id":           self.id,
            "user_id":      self.user_id,
            "service_name": self.service_name,
            "contact":      self.contact,
            "called_at":    self.called_at.isoformat(),
        }
