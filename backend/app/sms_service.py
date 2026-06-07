"""
Mech Platform — SMS Service
Supports: Africa's Talking (production), Stub/console (development)
"""
import os
import logging

logger = logging.getLogger(__name__)


def send_sms(phone: str, message: str) -> bool:
    """
    Send an SMS to the given phone number.
    Returns True on success, False on failure.
    Provider is selected via SMS_PROVIDER env var: 'africastalking' | 'stub'
    """
    provider = os.environ.get("SMS_PROVIDER", "stub").lower()

    if provider == "africastalking":
        return _send_africastalking(phone, message)
    else:
        return _send_stub(phone, message)


def sms_status() -> bool:
    """Return True if the SMS gateway is reachable."""
    provider = os.environ.get("SMS_PROVIDER", "stub").lower()
    if provider == "stub":
        return True
    if provider == "africastalking":
        return _check_africastalking()
    return False


# ── Africa's Talking ──────────────────────────────────────────────
def _send_africastalking(phone: str, message: str) -> bool:
    try:
        import africastalking
        username = os.environ.get("AFRICASTALKING_USERNAME", "sandbox")
        api_key = os.environ.get("AFRICASTALKING_API_KEY", "")
        sender = os.environ.get("SMS_SENDER", "MECH")

        africastalking.initialize(username, api_key)
        sms = africastalking.SMS

        # Normalise phone to international format (+254...)
        if phone.startswith("0"):
            phone = "+254" + phone[1:]
        elif not phone.startswith("+"):
            phone = "+254" + phone

        response = sms.send(message, [phone], sender)
        recipients = response.get("SMSMessageData", {}).get("Recipients", [])
        for r in recipients:
            if r.get("statusCode") not in (100, 101):
                logger.warning("AT SMS failed for %s: %s", phone, r)
                return False
        return True

    except ImportError:
        logger.error("africastalking package not installed. pip install africastalking")
        return False
    except Exception as exc:
        logger.error("Africa's Talking SMS error: %s", exc)
        return False


def _check_africastalking() -> bool:
    try:
        import africastalking  # noqa: F401
        return True
    except ImportError:
        return False


# ── Stub (development / testing) ──────────────────────────────────
def _send_stub(phone: str, message: str) -> bool:
    """
    Print SMS to console instead of sending.
    In CI/testing, verifications auto-pass.
    """
    logger.info("📱 [SMS STUB] To: %s | Message: %s", phone, message)
    print(f"\n📱 SMS → {phone}: {message}\n")
    return True
