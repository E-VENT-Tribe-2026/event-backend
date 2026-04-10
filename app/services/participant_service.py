from fastapi import HTTPException
from app.db.supabase_client import supabase


def join_event(user_id: str, event_id: str):

    # check if already joined
    existing = (
        supabase.table("event_participants")
        .select("*")
        .eq("user_id", user_id)
        .eq("event_id", event_id)
        .execute()
    )

    if existing.data:
        raise HTTPException(status_code=400, detail="User already joined event")

    response = (
        supabase.table("event_participants")
        .insert({
            "user_id": user_id,
            "event_id": event_id,
            "status": "going"
        })
        .execute()
    )

    return response.data


def leave_event(user_id: str, event_id: str):

    response = (
        supabase.table("event_participants")
        .delete()
        .eq("user_id", user_id)
        .eq("event_id", event_id)
        .execute()
    )

    return {"message": "Left event successfully"}


def get_event_participants(event_id: str):

    response = (
        supabase.table("event_participants")
        .select("user_id, status, profiles(full_name, avatar_url)")
        .eq("event_id", event_id)
        .execute()
    )

    return response.data

def get_my_events(user_id: str):
    response = supabase.table("event_participants") \
        .select("event_id, events(*)") \
        .eq("user_id", user_id) \
        .execute()
    return response.data or []  

def get_my_events(user_id: str):
    response = supabase.table("event_participants") \
        .select("event_id, events(*)") \
        .eq("user_id", user_id) \
        .execute()
    return response.data or []