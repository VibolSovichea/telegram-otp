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
            CREATE TABLE IF NOT EXISTS accounts (
                id            SERIAL PRIMARY KEY,
                provider      TEXT NOT NULL,
                provider_id   TEXT NOT NULL,
                email         TEXT UNIQUE NOT NULL,
                name          TEXT,
                avatar_url    TEXT,
                tier          TEXT DEFAULT 'free',
                created_at    TIMESTAMP DEFAULT NOW(),
                UNIQUE(provider, provider_id)
            );
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS apps (
                id            SERIAL PRIMARY KEY,
                app_id        TEXT UNIQUE NOT NULL,
                app_name      TEXT NOT NULL,
                app_secret    TEXT NOT NULL,
                account_id    INTEGER REFERENCES accounts(id) ON DELETE CASCADE,
                monthly_usage INTEGER DEFAULT 0,
                created_at    TIMESTAMP DEFAULT NOW()
            );
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS otp_logs (
                id                SERIAL PRIMARY KEY,
                session_id        TEXT NOT NULL,
                app_id            TEXT NOT NULL,
                telegram_user_id  TEXT,
                status            TEXT NOT NULL,
                created_at        TIMESTAMP DEFAULT NOW()
            );
        """)

        # Usage tracking — monthly rollup per app
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS usage_tracking (
                id          SERIAL PRIMARY KEY,
                app_id      TEXT NOT NULL,
                account_id  INTEGER REFERENCES accounts(id) ON DELETE CASCADE,
                month       TEXT NOT NULL,
                count       INTEGER DEFAULT 0,
                UNIQUE(app_id, month)
            );
        """)


async def get_or_create_account(
    provider: str, provider_id: str, email: str, name: str, avatar_url: str
) -> dict | None:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO accounts (provider, provider_id, email, name, avatar_url)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (provider, provider_id)
                DO UPDATE SET
                    email      = EXCLUDED.email,
                    name       = EXCLUDED.name,
                    avatar_url = EXCLUDED.avatar_url
                RETURNING *
            """,
                provider,
                provider_id,
                email,
                name,
                avatar_url,
            )
        return dict(row) if row else None
    except Exception as e:
        print(f"get_or_create_account error: {e}")
        return None


async def get_account_by_id(account_id: int) -> dict | None:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM accounts WHERE id = $1
            """,
                account_id,
            )
        return dict(row) if row else None
    except Exception as e:
        print(f"get_account_by_id error: {e}")
        return None


async def get_account_by_email(email: str) -> dict | None:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM accounts WHERE email = $1
            """,
                email,
            )
        return dict(row) if row else None
    except Exception as e:
        print(f"get_account_by_email error: {e}")
        return None


async def register_app(
    app_id: str, app_name: str, app_secret: str, account_id: int
) -> bool:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO apps (app_id, app_name, app_secret, account_id)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (app_id) DO NOTHING
            """,
                app_id,
                app_name,
                app_secret,
                account_id,
            )
        return True
    except Exception as e:
        print(f"register_app error: {e}")
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
    except Exception as e:
        print(f"get_app error: {e}")
        return None


async def get_apps_by_account(account_id: int) -> list:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    a.*,
                    COALESCE(u.count, 0) AS current_month_usage
                FROM apps a
                LEFT JOIN usage_tracking u
                    ON a.app_id = u.app_id
                    AND u.month = TO_CHAR(NOW(), 'YYYY-MM')
                WHERE a.account_id = $1
                ORDER BY a.created_at DESC
            """,
                account_id,
            )
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"get_apps_by_account error: {e}")
        return []


async def delete_app(app_id: str, account_id: int) -> bool:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM apps
                WHERE app_id = $1 AND account_id = $2
            """,
                app_id,
                account_id,
            )
        return result == "DELETE 1"
    except Exception as e:
        print(f"delete_app error: {e}")
        return False


async def rotate_app_secret(app_id: str, account_id: int, new_secret: str) -> bool:
    """
    Rotate the app secret. Scoped to account_id.
    Pro and Enterprise tier only — enforced at the route level.
    """
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE apps
                SET app_secret = $1
                WHERE app_id = $2 AND account_id = $3
            """,
                new_secret,
                app_id,
                account_id,
            )
        return result == "UPDATE 1"
    except Exception as e:
        print(f"rotate_app_secret error: {e}")
        return False


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
    except Exception as e:
        print(f"log_otp_event error: {e}")
        return False


async def get_otp_logs(
    app_id: str, account_id: int, limit: int = 50, offset: int = 0
) -> list:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT l.*
                FROM otp_logs l
                JOIN apps a ON l.app_id = a.app_id
                WHERE l.app_id = $1 AND a.account_id = $2
                ORDER BY l.created_at DESC
                LIMIT $3 OFFSET $4
            """,
                app_id,
                account_id,
                limit,
                offset,
            )
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"get_otp_logs error: {e}")
        return []


async def increment_usage(app_id: str, account_id: int) -> bool:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO usage_tracking (app_id, account_id, month, count)
                VALUES ($1, $2, TO_CHAR(NOW(), 'YYYY-MM'), 1)
                ON CONFLICT (app_id, month)
                DO UPDATE SET count = usage_tracking.count + 1
            """,
                app_id,
                account_id,
            )
        return True
    except Exception as e:
        print(f"increment_usage error: {e}")
        return False


async def get_usage_summary(account_id: int) -> list:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    a.app_id,
                    a.app_name,
                    COALESCE(u.count, 0) AS usage,
                    a.created_at
                FROM apps a
                LEFT JOIN usage_tracking u
                    ON a.app_id = u.app_id
                    AND u.month = TO_CHAR(NOW(), 'YYYY-MM')
                WHERE a.account_id = $1
                ORDER BY usage DESC
            """,
                account_id,
            )
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"get_usage_summary error: {e}")
        return []


async def get_quota_limit(tier: str) -> int:
    limits = {"free": 500, "pro": 10000, "enterprise": 999999999}
    return limits.get(tier, 500)
