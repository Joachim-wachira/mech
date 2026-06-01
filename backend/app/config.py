"""
Mech Platform — Configuration Classes
"""
import os
from datetime import timedelta


class BaseConfig:
    APP_NAME    = "mech"
    SECRET_KEY  = os.environ.get("SECRET_KEY", "mech-dev-secret-change-in-production")
    JWT_SECRET_KEY           = os.environ.get("JWT_SECRET_KEY", "mech-jwt-secret-change")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(days=30)

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle":  300,
    }

    SMS_PROVIDER            = os.environ.get("SMS_PROVIDER", "stub")
    AFRICASTALKING_USERNAME = os.environ.get("AFRICASTALKING_USERNAME", "sandbox")
    AFRICASTALKING_API_KEY  = os.environ.get("AFRICASTALKING_API_KEY", "")
    SMS_SENDER              = os.environ.get("SMS_SENDER", "MECH")

    NEARBY_RADIUS_KM   = float(os.environ.get("NEARBY_RADIUS_KM", "25"))
    UPLOAD_FOLDER      = os.environ.get("UPLOAD_FOLDER", "/tmp/mech_uploads")
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024   # 16 MB
    CURRENCY = "KES"


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///mech_dev.db")
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}


class ProductionConfig(BaseConfig):
    DEBUG = False

    # Build the URI at class definition time so Flask can read it as
    # a plain string attribute — fixes the Render postgres:// scheme bug.
    _raw_uri = os.environ.get("DATABASE_URL", "")
    SQLALCHEMY_DATABASE_URI = (
        _raw_uri.replace("postgres://", "postgresql://", 1)
        if _raw_uri.startswith("postgres://")
        else _raw_uri
    )

    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle":  300,
        "pool_size":     5,     # keep low — free Postgres has connection limits
        "max_overflow":  5,
    }


class TestingConfig(BaseConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_ENGINE_OPTIONS = {}
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=5)
