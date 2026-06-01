"""
Mech Platform — Marshmallow Schemas (request/response validation)
"""
from marshmallow import Schema, fields, validate, validates, ValidationError


class DriverRegistrationSchema(Schema):
    full_name     = fields.Str(required=True, validate=validate.Length(min=2, max=120))
    email         = fields.Email(required=True)
    phone         = fields.Str(required=True, validate=validate.Length(min=7, max=25))
    password      = fields.Str(required=True, validate=validate.Length(min=8))
    country       = fields.Str(load_default="")
    location_text = fields.Str(load_default="")
    location_lat  = fields.Float(load_default=None, allow_none=True)
    location_lng  = fields.Float(load_default=None, allow_none=True)
    terms_accepted = fields.Bool(load_default=False)

    @validates("terms_accepted")
    def must_accept_terms(self, value):
        if not value:
            raise ValidationError("You must accept the Terms and Conditions to register.")


class MechanicRegistrationSchema(Schema):
    full_name      = fields.Str(required=True, validate=validate.Length(min=2, max=120))
    email          = fields.Email(required=True)
    phone          = fields.Str(required=True, validate=validate.Length(min=7, max=25))
    password       = fields.Str(required=True, validate=validate.Length(min=8))
    business_name  = fields.Str(load_default="")
    country        = fields.Str(load_default="")
    location_text  = fields.Str(load_default="")
    location_lat   = fields.Float(load_default=None, allow_none=True)
    location_lng   = fields.Float(load_default=None, allow_none=True)
    vehicle_brands = fields.List(fields.Str(), load_default=[])
    services       = fields.List(fields.Str(), load_default=[])
    terms_accepted = fields.Bool(load_default=False)

    @validates("terms_accepted")
    def must_accept_terms(self, value):
        if not value:
            raise ValidationError("You must accept the Terms and Conditions to register.")


class SpareShopRegistrationSchema(Schema):
    full_name            = fields.Str(required=True, validate=validate.Length(min=2, max=120))
    email                = fields.Email(required=True)
    phone                = fields.Str(required=True, validate=validate.Length(min=7, max=25))
    password             = fields.Str(required=True, validate=validate.Length(min=8))
    business_name        = fields.Str(load_default="")
    country              = fields.Str(load_default="")
    location_text        = fields.Str(load_default="")
    location_lat         = fields.Float(load_default=None, allow_none=True)
    location_lng         = fields.Float(load_default=None, allow_none=True)
    inventory_categories = fields.List(fields.Str(), load_default=[])
    delivery_options     = fields.List(fields.Str(), load_default=[])
    delivery_km          = fields.Float(load_default=None, allow_none=True)
    terms_accepted       = fields.Bool(load_default=False)

    @validates("terms_accepted")
    def must_accept_terms(self, value):
        if not value:
            raise ValidationError("You must accept the Terms and Conditions to register.")


class LoginSchema(Schema):
    # Supports email OR phone via the "identifier" field
    identifier = fields.Str(load_default=None, allow_none=True)
    email      = fields.Str(load_default=None, allow_none=True)   # legacy fallback
    password   = fields.Str(required=True)


class SendSmsSchema(Schema):
    phone = fields.Str(required=True, validate=validate.Length(min=7, max=25))


class VerifySmsSchema(Schema):
    phone = fields.Str(required=True)
    code  = fields.Str(required=True, validate=validate.Length(min=4, max=10))


class JobRequestSchema(Schema):
    provider_id       = fields.Int(required=True)
    job_type          = fields.Str(required=True, validate=validate.OneOf(["mechanic","spareshop","rescue"]))
    vehicle_type      = fields.Str(load_default="")
    fault_description = fields.Str(load_default="")
    driver_lat        = fields.Float(load_default=None, allow_none=True)
    driver_lng        = fields.Float(load_default=None, allow_none=True)


class ReviewSchema(Schema):
    reviewee_id = fields.Int(required=True)
    job_id      = fields.Int(load_default=None, allow_none=True)
    rating      = fields.Int(required=True, validate=validate.Range(min=1, max=5))
    comment     = fields.Str(load_default="")


class MessageSchema(Schema):
    conversation_id = fields.Int(required=True)
    content         = fields.Str(required=True, validate=validate.Length(min=1))
    message_type    = fields.Str(load_default="text", validate=validate.OneOf(["text","image","voice","file"]))


class AdminNotifySchema(Schema):
    message   = fields.Str(required=True, validate=validate.Length(min=1))
    target    = fields.Str(load_default=None, allow_none=True)
    role      = fields.Str(load_default=None, allow_none=True)
    broadcast = fields.Bool(load_default=False)


class SuspendUserSchema(Schema):
    user_id        = fields.Int(required=True)
    duration_hours = fields.Int(required=True, validate=validate.Range(min=1, max=8760))


class AvailabilitySchema(Schema):
    available = fields.Bool(required=True)


class IssueReportSchema(Schema):
    description = fields.Str(required=True, validate=validate.Length(min=5))
    user_id     = fields.Int(load_default=None, allow_none=True)
