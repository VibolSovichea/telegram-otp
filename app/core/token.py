import hashlib
import hmac
import secrets
import time

from app.core.config import settings


def generate_short_token() -> str:
    return secrets.token_urlsafe(32)


def generate_nonce() -> str:
    return secrets.token_hex(16)


def generate_redis_hmac(
    token: str, session_id: str, app_id: str, nonce: str, timestamp: str
) -> str:
    raw = f"{token}:{session_id}:{app_id}:{nonce}:{timestamp}"
    return hmac.new(
        settings.APP_SECRET.encode(), raw.encode(), hashlib.sha256
    ).hexdigest()


def verify_redis_hmac(token: str, data: dict) -> bool:
    expected = generate_redis_hmac(
        token,
        data.get("session_id", ""),
        data.get("app_id", ""),
        data.get("nonce", ""),
        data.get("timestamp", ""),
    )
    stored = data.get("hmac", "")

    if not stored:
        return False

    return hmac.compare_digest(expected, stored)


def generate_otp_code(telegram_user_id: str, session_id: str, nonce: str) -> str:
    raw = f"{telegram_user_id}:{session_id}:{nonce}"
    digest = hmac.new(
        settings.APP_SECRET.encode(), raw.encode(), hashlib.sha256
    ).hexdigest()
    return digest[: settings.OTP_CODE_LENGTH].upper()


def is_token_expired(timestamp: str) -> bool:
    try:
        age = int(time.time()) - int(timestamp)
        return age > settings.OTP_EXPIRY_SECONDS
    except (ValueError, TypeError):
        return True


def is_claim_window_expired(claimed_at: str) -> bool:
    try:
        age = int(time.time()) - int(claimed_at)
        return age > 90
    except (ValueError, TypeError):
        return True
