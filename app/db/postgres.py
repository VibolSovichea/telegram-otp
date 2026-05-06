import asyncpg

from app.core.config import settings

_pool = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(settings.POSTGRES_URL)
    return _pool


async def init_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS apps (
                id          SERIAL PRIMARY KEY,
                app_id      TEXT UNIQUE NOT NULL,
                app_name    TEXT NOT NULL,
                app_secret  TEXT NOT NULL,
                created_at  TIMESTAMP DEFAULT NOW()
            );
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS otp_logs (
                id              SERIAL PRIMARY KEY,
                session_id      TEXT NOT NULL,
                app_id          TEXT NOT NULL,
                telegram_user_id TEXT,
                status          TEXT NOT NULL,  -- generated, claimed, validated, expired, failed
                created_at      TIMESTAMP DEFAULT NOW()
            );
        """)


async def register_app(app_id: str, app_name: str, app_secret: str) -> bool:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO apps (app_id, app_name, app_secret)
                VALUES ($1, $2, $3)
                ON CONFLICT (app_id) DO NOTHING
            """,
                app_id,
                app_name,
                app_secret,
            )
        return True
    except Exception:
        return False


async def get_app(app_id: str) -> dict | None:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM apps WHERE app_id = $1
            """,
                app_id,
            )
        return dict(row) if row else None
    except Exception:
        return None


async def log_otp_event(
    session_id: str, app_id: str, status: str, telegram_user_id: str = None
) -> bool:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO otp_logs (session_id, app_id, telegram_user_id, status)
                VALUES ($1, $2, $3, $4)
            """,
                session_id,
                app_id,
                telegram_user_id,
                status,
            )
        return True
    except Exception:
        return False


async def get_otp_logs(app_id: str, limit: int = 50) -> list:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM otp_logs
                WHERE app_id = $1
                ORDER BY created_at DESC
                LIMIT $2
            """,
                app_id,
                limit,
            )
        return [dict(row) for row in rows]
    except Exception:
        return []
