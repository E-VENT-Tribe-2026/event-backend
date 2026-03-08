from dotenv import load_dotenv
import os

load_dotenv()

class Settings:
    SUPABASE_URL: str = os.getenv("SUPABASE_URL")
    SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY")

settings = Settings()

if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_KEY:
    raise ValueError("Supabase configuration is missing in .env")