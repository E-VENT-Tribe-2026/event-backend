from supabase import create_client
from app.core.config import settings

supabase = None

if settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLEKEY:
    supabase = create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_SERVICE_KEY
    )