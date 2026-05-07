from pydantic_settings import BaseSettings

class Settings(BaseSettings):
  TELEGRAM_BOT_TOKEN: str
  TELEGRAM_BOT_USERNAME: str
  APP_SECRET: str
  REDIS_URL: str
  POSTGRES_URL: str
  OTP_EXPIRY_SECONDS: int = 60
  OTP_CODE_LENGTH: int = 6

  NEXTAUTH_SECRET: str
  NEXTAUTH_URL: str = "http://localhost:3000"

  GITHUB_CLIENT_ID: str
  GITHUB_CLIENT_SECRET: str

  GOOGLE_CLIENT_ID: str
  GOOGLE_CLIENT_SECRET: str

  class Config:
    env_file = ".env"

settings = Settings()
