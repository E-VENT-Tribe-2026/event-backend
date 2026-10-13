from supabase import create_client
from app.core.config import settings

supabase = None

if settings.SUPABASE_URL and settings.SUPABASE_SERVICE_KEY:
    supabase = create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_SERVICE_KEY
    )
    # Prevent sign-in / auth events from downgrading the service_role key to a user session
    supabase._listen_to_auth_events = lambda event, session: None
    if hasattr(supabase.auth, "_state_change_emitters"):
        supabase.auth._state_change_emitters.clear()

