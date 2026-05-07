from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from app.core.config import settings
from app.core.token import (
    generate_otp_code,
    is_token_expired,
    verify_redis_hmac,
)
from app.db.postgres import get_app, log_otp_event
from app.db.redis import (
    get_token,
    is_claim_rate_limited,
    mark_token_claimed,
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_user_id = str(update.effective_user.id)
    if await is_claim_rate_limited(telegram_user_id):
        await update.message.reply_text(
            "⚠️ Too many attempts.\n\n"
            "You have made too many requests in a short period. "
            "Please wait a few minutes before trying again."
        )
        return

    if not context.args:
        await update.message.reply_text(
            "👋 Welcome to OTPGram.\n\n"
            "This bot delivers one-time authentication codes for applications "
            "that have integrated the OTPGram service.\n\n"
            "If you were trying to authenticate, please return to the "
            "application and request a new code."
        )
        return

    token = context.args[0]
    token_data = await get_token(token)
    if not token_data:
        await update.message.reply_text(
            "❌ This link is invalid or has expired.\n\n"
            "Please return to the application and request a new code."
        )
        return

    session_id = token_data.get("session_id")
    app_id = token_data.get("app_id")
    nonce = token_data.get("nonce")

    if not verify_redis_hmac(token, token_data):
        await update.message.reply_text(
            "❌ This link is invalid or has expired.\n\n"
            "Please return to the application and request a new code."
        )
        await log_otp_event(session_id, app_id, "failed", telegram_user_id)
        return

    if is_token_expired(token_data.get("timestamp", "0")):
        await update.message.reply_text(
            "❌ This session has expired.\n\n"
            "Please return to the application and request a new code."
        )
        await log_otp_event(session_id, app_id, "expired", telegram_user_id)
        return

    if token_data.get("claimed") == "true":
        await update.message.reply_text(
            "⚠️ This code has already been claimed.\n\n"
            "Each authentication link can only be used once. "
            "If this was not you, please contact the application support immediately."
        )
        await log_otp_event(session_id, app_id, "failed", telegram_user_id)
        return

    app = await get_app(app_id)
    if not app:
        await update.message.reply_text(
            "❌ This application is not registered with OTPGram.\n\n"
            "Please contact the application support."
        )
        await log_otp_event(session_id, app_id, "failed", telegram_user_id)
        return

    claimed = await mark_token_claimed(token, telegram_user_id)
    if not claimed:
        await update.message.reply_text("⚠️ Something went wrong. Please try again.")
        return

    await log_otp_event(session_id, app_id, "claimed", telegram_user_id)

    otp_code = generate_otp_code(telegram_user_id, session_id, nonce)

    await update.message.reply_text(
        f"🔐 *{app['app_name']}* is requesting verification.\n\n"
        f"Your one-time code is:\n\n"
        f"`{otp_code}`\n\n"
        f"⏱ This code expires in *90 seconds*.\n"
        f"🚫 Do not share this code with anyone.\n\n"
        f"_If you did not request this code, ignore this message._",
        parse_mode="Markdown",
    )


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"Bot error: {context.error}")
    if update and update.message:
        await update.message.reply_text(
            "⚠️ Something went wrong on our end. Please try again."
        )


def create_bot_app() -> Application:
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_error_handler(error_handler)

    return app
