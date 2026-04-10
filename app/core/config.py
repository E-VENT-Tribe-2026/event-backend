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

    class Config:
        env_file = ".env"
        case_sensitive = True
        # This prevents the "extra_forbidden" error by ignoring 
        # any .env variables not defined above.
        extra = "ignore" 

settings = Settings()