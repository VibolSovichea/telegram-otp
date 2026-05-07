import time

import redis.asyncio as redis

from app.core.config import settings
from app.core.token import generate_nonce, generate_redis_hmac, generate_short_token

_redis_client = None


async def get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = await redis.from_url(
            settings.REDIS_URL, encoding="utf-8", decode_responses=True
        )
    return _redis_client


async def store_token(session_id: str, app_id: str) -> str:
    client = await get_redis()

    token = generate_short_token()
    nonce = generate_nonce()
    timestamp = str(int(time.time()))

    integrity_hmac = generate_redis_hmac(token, session_id, app_id, nonce, timestamp)

    key = f"otp:{token}"
    await client.hset(
        key,
        mapping={
            "session_id": session_id,
            "app_id": app_id,
            "nonce": nonce,
            "timestamp": timestamp,
            "claimed": "false",
            "claimed_at": "",
            "telegram_user_id": "",
            "hmac": integrity_hmac,
        },
    )
    await client.expire(key, settings.OTP_EXPIRY_SECONDS)

    return token


async def get_token(token: str) -> dict | None:
    try:
        client = await get_redis()
        key = f"otp:{token}"
        data = await client.hgetall(key)
        return data if data else None
    except Exception:
        return None


async def get_token_by_session(session_id: str) -> tuple[str, dict] | None:
    try:
        client = await get_redis()
        async for key in client.scan_iter("otp:*"):
            data = await client.hgetall(key)
            if data.get("session_id") == session_id:
                token = key.replace("otp:", "")
                return token, data
        return None
    except Exception:
        return None


async def mark_token_claimed(token: str, telegram_user_id: str) -> bool:
    try:
        client = await get_redis()
        key = f"otp:{token}"
        await client.hset(
            key,
            mapping={
                "telegram_user_id": telegram_user_id,
                "claimed": "true",
                "claimed_at": str(int(time.time())),
            },
        )
        return True
    except Exception:
        return False


async def consume_token(token: str) -> bool:
    try:
        client = await get_redis()
        result = await client.delete(f"otp:{token}")
        return result > 0
    except Exception:
        return False


async def is_claim_rate_limited(telegram_user_id: str) -> bool:
    try:
        client = await get_redis()
        key = f"ratelimit:claim:{telegram_user_id}"
        attempts = await client.incr(key)
        if attempts == 1:
            await client.expire(key, 600)  # 10 minute window
        return attempts > 5
    except Exception:
        return False


async def increment_failed_attempts(session_id: str) -> int:
    try:
        client = await get_redis()
        key = f"attempts:{session_id}"
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, settings.OTP_EXPIRY_SECONDS)
        return count
    except Exception:
        return 0


async def is_session_locked(session_id: str) -> bool:
    try:
        client = await get_redis()
        key = f"attempts:{session_id}"
        count = await client.get(key)
        return int(count) >= 3 if count else False
    except Exception:
        return False
