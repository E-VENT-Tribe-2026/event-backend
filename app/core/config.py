from dotenv import load_dotenv
load_dotenv()

from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "E-VENT Orchestrator"
    
    # Existing required fields
    DATABASE_URL: str
    SUPABASE_URL: str
    SUPABASE_SERVICE_KEY: str

    # Add these missing fields to match your .env
    SUPABASE_JWT_SECRET: str
    BACKEND_URL: str
    FRONTEND_URL: str
    
    # Optional: If you have the Mixedbread key in .env, add it here too
    MXBAI_API_KEY: Optional[str] = None

    # Email / SMTP settings
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    EMAIL_FROM: str = "no-reply@eventapp.com"

    class Config:
        env_file = ".env"
        case_sensitive = True
        # This prevents the "extra_forbidden" error by ignoring 
        # any .env variables not defined above.
        extra = "ignore" 

settings = Settings()