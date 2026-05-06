import hashlib
import hmac
import secrets
import time

from app.core.config import settings


def generate_payload(session_id: str, app_id: str) -> str:
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(8)
    raw = f"{session_id}:{app_id}:{timestamp}:{nonce}"
    signature = hmac.new(
        settings.APP_SECRET.encode(), raw.encode(), hashlib.sha256
    ).hexdigest()

    payload = f"{session_id}.{app_id}.{timestamp}.{nonce}.{signature}"
    return payload


def generate_otp_code(telegram_usr_id: str, session_id: str, nonce: str) -> str:
    raw = f"{telegram_usr_id}:{session_id}:{nonce}"

    digest = hmac.new(
        settings.APP_SECRET.encode(), raw.encode(), hashlib.sha256
    ).hexdigest()

    code = digest[: settings.OTP_CODE_LENGTH].upper()
    return code


def verify_payload(payload: str) -> dict | None:
    try:
        session_id, app_id, timestamp, nonce, signature = payload.split(".")
    except ValueError:
        return None

    age = int(time.time()) - int(timestamp)
    if age > settings.OTP_EXPIRY_SECONDS:
        return None

    raw = f"{session_id}:{app_id}:{timestamp}:{nonce}"
    expected_signature = hmac.new(
        settings.APP_SECRET.encode(), raw.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, signature):
        return None

    return {
        "session_id": session_id,
        "app_id": app_id,
        "timestamp": timestamp,
        "nonce": nonce,
    }
