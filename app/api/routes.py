import secrets

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.core.config import settings
from app.core.token import (
    generate_otp_code,
    is_claim_window_expired,
    is_token_expired,
    verify_redis_hmac,
)
from app.db.postgres import get_app, log_otp_event, register_app
from app.db.redis import (
    consume_token,
    get_token_by_session,
    increment_failed_attempts,
    is_session_locked,
    store_token,
)

router = APIRouter()


class GenerateOTPRequest(BaseModel):
    app_id: str
    session_id: str


class ValidateOTPRequest(BaseModel):
    session_id: str
    otp_code: str


class RegisterAppRequest(BaseModel):
    app_id: str
    app_name: str


class GenerateOTPResponse(BaseModel):
    deep_link: str
    expires_in: int


class ValidateOTPResponse(BaseModel):
    valid: bool
    message: str


class RegisterAppResponse(BaseModel):
    app_id: str
    app_secret: str
    message: str


@router.post("/register", response_model=RegisterAppResponse)
async def register(request: RegisterAppRequest):
    existing = await get_app(request.app_id)
    if existing:
        raise HTTPException(status_code=400, detail="App ID already registered.")

    app_secret = secrets.token_hex(32)

    success = await register_app(request.app_id, request.app_name, app_secret)
    if not success:
        raise HTTPException(
            status_code=500, detail="Failed to register app. Please try again."
        )

    return RegisterAppResponse(
        app_id=request.app_id,
        app_secret=app_secret,
        message=(
            "App registered successfully. "
            "Store your app_secret securely — it will not be shown again."
        ),
    )


@router.post("/generate", response_model=GenerateOTPResponse)
async def generate_otp(request: GenerateOTPRequest, x_app_secret: str = Header(...)):
    app = await get_app(request.app_id)
    if not app:
        raise HTTPException(status_code=401, detail="App not registered.")

    if not secrets.compare_digest(app["app_secret"], x_app_secret):
        raise HTTPException(status_code=401, detail="Invalid app secret.")

    token = await store_token(request.session_id, request.app_id)

    await log_otp_event(request.session_id, request.app_id, "generated")
    deep_link = f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start={token}"

    return GenerateOTPResponse(
        deep_link=deep_link, expires_in=settings.OTP_EXPIRY_SECONDS
    )


@router.post("/validate", response_model=ValidateOTPResponse)
async def validate_otp(request: ValidateOTPRequest, x_app_secret: str = Header(...)):
    if await is_session_locked(request.session_id):
        await log_otp_event(request.session_id, "unknown", "failed")
        raise HTTPException(
            status_code=429,
            detail=(
                "This session has been locked due to too many failed attempts. "
                "Please return to the application and request a new code."
            ),
        )

    result = await get_token_by_session(request.session_id)
    if not result:
        raise HTTPException(status_code=404, detail="Session not found or has expired.")

    token, token_data = result
    app_id = token_data.get("app_id")

    app = await get_app(app_id)
    if not app:
        raise HTTPException(status_code=401, detail="App not registered.")

    if not secrets.compare_digest(app["app_secret"], x_app_secret):
        raise HTTPException(status_code=401, detail="Invalid app secret.")

    if not verify_redis_hmac(token, token_data):
        await log_otp_event(request.session_id, app_id, "failed")
        raise HTTPException(status_code=400, detail="Session integrity check failed.")

    if is_token_expired(token_data.get("timestamp", "0")):
        await log_otp_event(request.session_id, app_id, "expired")
        return ValidateOTPResponse(
            valid=False, message="Session has expired. Please request a new code."
        )

    if token_data.get("claimed") != "true":
        return ValidateOTPResponse(
            valid=False, message="OTP has not been claimed via Telegram yet."
        )

    telegram_user_id = token_data.get("telegram_user_id")
    if not telegram_user_id:
        return ValidateOTPResponse(
            valid=False, message="No Telegram user associated with this session."
        )

    if is_claim_window_expired(token_data.get("claimed_at", "0")):
        await log_otp_event(request.session_id, app_id, "expired", telegram_user_id)
        return ValidateOTPResponse(
            valid=False,
            message="Code has expired. You have 90 seconds from receiving the code to submit it.",
        )

    nonce = token_data.get("nonce")
    expected_code = generate_otp_code(telegram_user_id, request.session_id, nonce)

    if not secrets.compare_digest(expected_code, request.otp_code.upper()):
        attempts = await increment_failed_attempts(request.session_id)
        await log_otp_event(request.session_id, app_id, "failed", telegram_user_id)

        remaining = max(0, 3 - attempts)
        if remaining == 0:
            return ValidateOTPResponse(
                valid=False,
                message=(
                    "Invalid code. This session has been locked. "
                    "Please return to the application and request a new code."
                ),
            )

        return ValidateOTPResponse(
            valid=False,
            message=f"Invalid code. {remaining} attempt{'s' if remaining > 1 else ''} remaining.",
        )

    await consume_token(token)
    await log_otp_event(request.session_id, app_id, "validated", telegram_user_id)

    return ValidateOTPResponse(valid=True, message="OTP validated successfully.")
