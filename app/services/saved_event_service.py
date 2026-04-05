from fastapi import HTTPException
from app.db.supabase_client import supabase


def save_event(user_id: str, event_id: str):
    existing = supabase.table("saved_events") \
        .select("id") \
        .eq("user_id", user_id) \
        .eq("event_id", event_id) \
        .execute()

    if existing.data:
        raise HTTPException(status_code=400, detail="Event already saved")

    supabase.table("saved_events").insert({
        "user_id": user_id,
        "event_id": event_id
    }).execute()

    return {"message": "Event saved"}


def remove_saved_event(user_id: str, event_id: str):
    supabase.table("saved_events") \
        .delete() \
        .eq("user_id", user_id) \
        .eq("event_id", event_id) \
        .execute()

    return {"message": "Removed from saved events"}


def get_saved_events(user_id: str):
    response = supabase.table("saved_events") \
        .select("events(*)") \
        .eq("user_id", user_id) \
        .execute()

    return [item["events"] for item in response.data]