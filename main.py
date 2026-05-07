from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.bot.handlers import create_bot_app
from app.core.config import settings
from app.db.postgres import init_db
from app.api.portal import portal_router

bot_app = create_bot_app()


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting up...")

    print("Initializing database...")
    await init_db()
    print("Database ready.")

    print("Starting Telegram bot...")
    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling()
    print("Telegram bot running.")

    print("System ready.")

    yield

    print("Shutting down...")
    await bot_app.updater.stop()
    await bot_app.stop()
    await bot_app.shutdown()
    print("Shutdown complete.")


app = FastAPI(
    title="Telegram OTP Service",
    description="A lightweight OTP service using Telegram bot as the delivery channel.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")
app.include_router(portal_router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "bot": settings.TELEGRAM_BOT_USERNAME}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
