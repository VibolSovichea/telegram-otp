import redis.asyncio as redis

from app.core.config import settings

_redis_client = None


async def get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = await redis.from_url(
            settings.REDIS_URL, encoding="utf-8", decode_responses=True
        )
    return _redis_client


async def store_token(session_id: str, data: dict) -> bool:
    try:
        client = await get_redis()
        key = f"otp:{session_id}"

        await client.hset(key, mapping=data)
        await client.expire(key, settings.OTP_EXPIRY_SECONDS)

        return True
    except Exception:
        return False


async def get_token(session_id: str) -> dict | None:
    try:
        client = await get_redis()
        key = f"otp:{session_id}"

        data = await client.hgetall(key)
        return data if data else None
    except Exception:
        return None


async def consume_token(session_id: str) -> bool:
    try:
        client = await get_redis()
        key = f"otp:{session_id}"

        result = await client.delete(key)
        return result > 0
    except Exception:
        return False


async def mark_token_claimed(session_id: str, telegram_user_id: str) -> bool:
    try:
        client = await get_redis()
        key = f"otp:{session_id}"

        await client.hset(key, "telegram_user_id", telegram_user_id)
        await client.hset(key, "claimed", "true")

        return True
    except Exception:
        return False
