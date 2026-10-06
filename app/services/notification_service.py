from datetime import datetime, timezone
from app.db.supabase_client import supabase
from app.services.profile_service import get_user_summaries


def create_notification(
    user_id: str,
    event_id: str | None,
    type_: str,
    message: str,
    related_user_id: str | None = None,
):
    payload = {
        "user_id": user_id,
        "event_id": event_id,
        "type": type_,
        "message": message,
        "is_read": False,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    if related_user_id is not None:
        payload["related_user_id"] = related_user_id

    dedupe = supabase.table("notifications") \
        .select("created_at") \
        .eq("user_id", user_id)
    if event_id is None:
        dedupe = dedupe.is_("event_id", "null")
    else:
        dedupe = dedupe.eq("event_id", event_id)
    dedupe = dedupe.eq("type", type_).eq("message", message)
    if related_user_id is not None:
        dedupe = dedupe.eq("related_user_id", related_user_id)
    existing = dedupe \
        .order("created_at", desc=True) \
        .limit(1) \
        .execute()

    if existing.data:
        created_at = existing.data[0].get("created_at")

        # Guardrail: If a duplicate exists but has no timestamp, skip insertion
        if not created_at:
            return
        
        if isinstance(created_at, str):
            last_time = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        elif isinstance(created_at, datetime):
            last_time = created_at
        else:
            last_time = None

        if last_time:
            # Ensure last_time is timezone-aware before comparing
            if last_time.tzinfo is None:
                last_time = last_time.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            if (now - last_time).total_seconds() < 10:
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

    rows = response.data or []
    related_ids = [r["related_user_id"] for r in rows if r.get("related_user_id")]
    summaries = get_user_summaries(related_ids) if related_ids else {}
    for row in rows:
        rid = row.get("related_user_id")
        row["related_user"] = summaries.get(rid) if rid else None

    return {
        "page": page,
        "limit": limit,
        "data": rows
    }


def delete_notifications_for(user_id: str, type_: str, related_user_id: str):
    """Delete a user's notifications of one type that relate to a given other user."""
    response = supabase.table("notifications") \
        .delete() \
        .eq("user_id", user_id) \
        .eq("type", type_) \
        .eq("related_user_id", related_user_id) \
        .execute()
    return response.data or []


def mark_as_read(notification_id: int, user_id: str):
    return supabase.table("notifications") \
        .update({"is_read": True}) \
        .eq("id", notification_id) \
        .eq("user_id", user_id) \
        .execute()


def delete_notification(notification_id: int, user_id: str):
    response = supabase.table("notifications") \
        .delete() \
        .eq("id", notification_id) \
        .eq("user_id", user_id) \
        .execute()

    if not response.data:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Notification not found")

    return {"message": "Notification deleted"}


def delete_all_notifications(user_id: str):
    supabase.table("notifications") \
        .delete() \
        .eq("user_id", user_id) \
        .execute()

    return {"message": "All notifications deleted"}


def mark_all_as_read(user_id: str):
    supabase.table("notifications") \
        .update({"is_read": True}) \
        .eq("user_id", user_id) \
        .eq("is_read", False) \
        .execute()
    return {"message": "All notifications marked as read"}


def delete_selected_notifications(notification_ids: list[int], user_id: str):
    supabase.table("notifications") \
        .delete() \
        .eq("user_id", user_id) \
        .in_("id", notification_ids) \
        .execute()

    return {"message": "Selected notifications deleted"}
