import jwt
from fastapi import Header, HTTPException

from app.core.config import settings
from app.db.postgres import get_account_by_id


def create_portal_token(account_id: int) -> str:
    import time

    payload = {
        "account_id": account_id,
        "exp": int(time.time()) + 3600,
    }
    return jwt.encode(payload, settings.NEXTAUTH_SECRET, algorithm="HS256")


async def verify_portal_token(authorization: str = Header(...)) -> dict:
    try:
        scheme, token = authorization.split(" ")
        if scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Invalid authorization scheme.")

        payload = jwt.decode(token, settings.NEXTAUTH_SECRET, algorithms=["HS256"])
        account_id = payload.get("account_id")
        if not account_id:
            raise HTTPException(status_code=401, detail="Invalid token payload.")

        account = await get_account_by_id(account_id)
        if not account:
            raise HTTPException(status_code=401, detail="Account not found.")

        return account

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token.")
    except Exception:
        raise HTTPException(status_code=401, detail="Authorization failed.")
