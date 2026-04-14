from datetime import datetime, timezone
from app.db.supabase_client import supabase


def create_notification(user_id: str, event_id: str, type_: str, message: str):
    payload = {
        "user_id": user_id,
        "event_id": event_id,
        "type": type_,
        "message": message,
        "is_read": False,
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    # Prevent duplicates
    existing = supabase.table("notifications") \
        .select("id") \
        .eq("user_id", user_id) \
        .eq("event_id", event_id) \
        .eq("type", type_) \
        .execute()

    if existing.data:
        return

    supabase.table("notifications").insert(payload).execute()


def get_notifications(user_id: str, page: int = 1, limit: int = 10):
    start = (page - 1) * limit
    end = start + limit - 1

    response = supabase.table("notifications") \
        .select("*") \
        .eq("user_id", user_id) \
        .order("created_at", desc=True) \
        .range(start, end) \
        .execute()

    return {
        "page": page,
        "limit": limit,
        "data": response.data
    }


def mark_as_read(notification_id: int, user_id: str):
    return supabase.table("notifications") \
        .update({"is_read": True}) \
        .eq("id", notification_id) \
        .eq("user_id", user_id) \
        .execute()