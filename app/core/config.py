from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "E-VENT Orchestrator"
    
    # By defining these without defaults, Pydantic will RAISE an error 
    # automatically if they aren't found in your .env
    DATABASE_URL: str
    SUPABASE_URL: str
    SUPABASE_SERVICE_KEY: str

    class Config:
        env_file = ".env" #
        case_sensitive = True

# This will now throw a clear ValidationError if your .env is wrong
settings = Settings()