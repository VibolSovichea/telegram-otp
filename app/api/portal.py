import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import verify_portal_token
from app.db.postgres import (
    delete_app,
    get_app,
    get_apps_by_account,
    get_otp_logs,
    get_quota_limit,
    get_usage_summary,
    register_app,
    rotate_app_secret,
)

portal_router = APIRouter()


class CreateAppRequest(BaseModel):
    app_id: str
    app_name: str


@portal_router.get("/account/me")
async def get_me(account: dict = Depends(verify_portal_token)):
    return {
        "id": account["id"],
        "email": account["email"],
        "name": account["name"],
        "avatar_url": account["avatar_url"],
        "tier": account["tier"],
        "created_at": str(account["created_at"]),
    }


@portal_router.get("/portal/apps")
async def list_apps(account: dict = Depends(verify_portal_token)):
    apps = await get_apps_by_account(account["id"])
    return {"apps": apps}


@portal_router.post("/portal/apps")
async def create_app(
    request: CreateAppRequest, account: dict = Depends(verify_portal_token)
):
    existing_apps = await get_apps_by_account(account["id"])

    tier_app_limits = {"free": 1, "pro": 5, "enterprise": 999}
    limit = tier_app_limits.get(account["tier"], 1)

    if len(existing_apps) >= limit:
        raise HTTPException(
            status_code=403,
            detail=f"Your {account['tier']} plan allows a maximum of {limit} app{'s' if limit > 1 else ''}. Please upgrade to add more.",
        )

    existing = await get_app(request.app_id)
    if existing:
        raise HTTPException(status_code=400, detail="App ID already taken.")

    app_secret = secrets.token_hex(32)
    success = await register_app(
        request.app_id, request.app_name, app_secret, account["id"]
    )

    if not success:
        raise HTTPException(status_code=500, detail="Failed to create app.")

    return {
        "app_id": request.app_id,
        "app_name": request.app_name,
        "app_secret": app_secret,
        "message": "App created. Store your app_secret securely — it will not be shown again.",
    }


@portal_router.delete("/portal/apps/{app_id}")
async def remove_app(app_id: str, account: dict = Depends(verify_portal_token)):
    success = await delete_app(app_id, account["id"])
    if not success:
        raise HTTPException(
            status_code=404, detail="App not found or does not belong to your account."
        )
    return {"message": f"App {app_id} deleted successfully."}


@portal_router.post("/portal/apps/{app_id}/rotate-secret")
async def rotate_secret(app_id: str, account: dict = Depends(verify_portal_token)):
    if account["tier"] == "free":
        raise HTTPException(
            status_code=403,
            detail="Secret rotation is a Pro feature. Please upgrade your plan.",
        )

    new_secret = secrets.token_hex(32)
    success = await rotate_app_secret(app_id, account["id"], new_secret)
    if not success:
        raise HTTPException(
            status_code=404, detail="App not found or does not belong to your account."
        )

    return {
        "app_secret": new_secret,
        "message": "Secret rotated successfully. Update your integration immediately.",
    }


@portal_router.get("/portal/apps/{app_id}/logs")
async def get_logs(
    app_id: str,
    limit: int = 50,
    offset: int = 0,
    account: dict = Depends(verify_portal_token),
):
    logs = await get_otp_logs(app_id, account["id"], limit, offset)
    return {"logs": logs}


@portal_router.get("/portal/usage")
async def get_usage(account: dict = Depends(verify_portal_token)):
    summary = await get_usage_summary(account["id"])
    quota = await get_quota_limit(account["tier"])

    total_usage = sum(row["usage"] for row in summary)

    return {
        "tier": account["tier"],
        "quota": quota,
        "total_usage": total_usage,
        "remaining": max(0, quota - total_usage),
        "apps": summary,
    }
