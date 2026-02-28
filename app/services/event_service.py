from app.db.supabase_client import supabase

def get_all_events():
    response = supabase.table("events").select("*").execute()
    return response.data

def create_event(event_data: dict, user_id: str):
    event_data["created_by"] = user_id
    response = supabase.table("events").insert(event_data).execute()
    return response.data