from dotenv import load_dotenv
load_dotenv()

from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from typing import Optional


class Settings(BaseSettings):
    model_config = ConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )

    PROJECT_NAME: str = "E-VENT Orchestrator"

    # Required fields
    DATABASE_URL: str
    SUPABASE_URL: str
    SUPABASE_SERVICE_KEY: str
    SUPABASE_ANON_KEY: Optional[str] = None

    SUPABASE_JWT_SECRET: str
    BACKEND_URL: str
    FRONTEND_URL: str

    # Optional extras
    MXBAI_API_KEY: Optional[str] = None

    # Email / SMTP settings
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    EMAIL_FROM: str = "no-reply@eventapp.com"

    CRON_SECRET: Optional[str] = None


settings = Settings()