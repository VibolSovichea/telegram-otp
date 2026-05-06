from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, ContextTypes

from app.core.config import settings
from app.core.token import generate_otp_code, verify_payload
from app.db.postgres import get_app, log_otp_event
from app.db.redis import get_token, mark_token_claimed, store_token


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "👋 Welcome to the OTP Bot.\n\n"
            "This bot is used to receive one-time passwords for applications "
            "that have integrated this service.\n\n"
            "If you were trying to authenticate, please return to the "
            "application and try again."
        )
        return

    payload = context.args[0]
    telegram_user_id = str(update.effective_user.id)

    parsed = verify_payload(payload)
    if not parsed:
        await update.message.reply_text(
            "❌ This link is invalid or has expired.\n\n"
            "Please return to the application and try again."
        )
        return

    session_id = parsed["session_id"]
    app_id = parsed["app_id"]
    nonce = parsed["nonce"]

    token_data = await get_token(session_id)
    if not token_data:
        await update.message.reply_text(
            "❌ This session has expired.\n\n"
            "Please return to the application and request a new code."
        )
        await log_otp_event(session_id, app_id, "expired")
        return

    if token_data.get("claimed") == "true":
        await update.message.reply_text(
            "⚠️ This code has already been claimed.\n\n"
            "If this wasn't you, please contact the application support."
        )
        await log_otp_event(session_id, app_id, "failed", telegram_user_id)
        return

    app = await get_app(app_id)
    if not app:
        await update.message.reply_text(
            "❌ This application is not registered.\n\n"
            "Please contact the application support."
        )
        await log_otp_event(session_id, app_id, "failed", telegram_user_id)
        return

    await mark_token_claimed(session_id, telegram_user_id)
    await log_otp_event(session_id, app_id, "claimed", telegram_user_id)

    otp_code = generate_otp_code(telegram_user_id, session_id, nonce)

    await update.message.reply_text(
        f"🔐 *{app['app_name']}* is requesting verification.\n\n"
        f"Your one-time code is:\n\n"
        f"`{otp_code}`\n\n"
        f"⏱ This code expires in {settings.OTP_EXPIRY_SECONDS // 60} minutes.\n"
        f"🚫 Do not share this code with anyone.",
        parse_mode="Markdown",
    )


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"Bot error: {context.error}")
    if update and update.message:
        await update.message.reply_text("⚠️ Something went wrong. Please try again.")


def create_bot_app() -> Application:
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_error_handler(error_handler)

    return app
