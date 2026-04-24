from fastapi import HTTPException
from app.db.supabase_client import supabase
from app.services.notification_service import create_notification
from app.services.event_service import get_event
from app.services.chat_service import post_system_notification


def _get_display_name(user_id: str) -> str:
    """Return the user's full_name from profiles, falling back to a short ID."""
    try:
        result = (
            supabase.table("profiles")
            .select("full_name")
            .eq("id", user_id)
            .single()
            .execute()
        )
        name = result.data.get("full_name") if result.data else None
        return name if name else user_id[:8]
    except Exception:
        return user_id[:8]


def join_event(user_id: str, event_id: str):

    event = get_event(event_id)

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

    # Post system notification in the event chat
    display_name = _get_display_name(user_id)
    post_system_notification(event_id, f"👋 {display_name} has joined this chat")

    create_notification(
        event["created_by"],
        event_id,
        "user_joined",
        f"User {user_id} joined your event '{event['title']}'"
    )

    return response.data


def leave_event(user_id: str, event_id: str):
    event = get_event(event_id)
    response = (
        supabase.table("event_participants")
        .delete()
        .eq("user_id", user_id)
        .eq("event_id", event_id)
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=400, detail="User not part of event")

    create_notification(
        event["created_by"],
        event_id,
        "user_left",
        f"User {user_id} left your event '{event['title']}'"
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