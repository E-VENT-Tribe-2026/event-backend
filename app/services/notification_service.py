import logging
from datetime import datetime, timezone
from app.db.supabase_client import supabase
from app.services.profile_service import get_user_summaries

logger = logging.getLogger(__name__)

_OPTIONAL_NOTIFICATION_COLUMNS = ("actor_id", "friend_request_id", "related_user_id")


def _is_missing_column_error(exc: Exception, col: str) -> bool:
    code = str(getattr(exc, "code", "") or "")
    text = str(exc)
    msg = str(getattr(exc, "message", "") or "")
    is_missing_code = (
        code in {"42703", "PGRST204"}
        or "42703" in text
        or "PGRST204" in text
        or "schema cache" in text.lower()
    )
    return is_missing_code and (col in text or col in msg)


def create_notification(
    user_id: str,
    event_id: str | None,
    type_: str,
    message: str,
    related_user_id: str | None = None,
    actor_id: str | None = None,
    friend_request_id: int | None = None,
):
    if actor_id is None and related_user_id is not None:
        actor_id = related_user_id

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
    if actor_id is not None:
        payload["actor_id"] = actor_id
    if friend_request_id is not None:
        payload["friend_request_id"] = friend_request_id

    def _query_dedupe(use_related_col: bool = True):
        dedupe = supabase.table("notifications") \
            .select("created_at") \
            .eq("user_id", user_id)
        if event_id is None:
            dedupe = dedupe.is_("event_id", "null")
        else:
            dedupe = dedupe.eq("event_id", event_id)
        dedupe = dedupe.eq("type", type_).eq("message", message)
        if related_user_id is not None:
            if use_related_col:
                dedupe = dedupe.eq("related_user_id", related_user_id)
            elif actor_id is not None:
                dedupe = dedupe.eq("actor_id", actor_id)
        return dedupe.order("created_at", desc=True).limit(1).execute()

    try:
        existing = _query_dedupe(use_related_col=True)
    except Exception as e:
        if _is_missing_column_error(e, "related_user_id"):
            existing = _query_dedupe(use_related_col=False)
        else:
            raise

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
    try:
        supabase.table("notifications").insert(payload).execute()
        return
    except Exception as e:
        if _is_missing_column_error(e, "related_user_id") and "related_user_id" in payload:
            fallback_payload = {k: v for k, v in payload.items() if k != "related_user_id"}
            try:
                supabase.table("notifications").insert(fallback_payload).execute()
                return
            except Exception:
                pass
        stripped = {k: v for k, v in payload.items() if k not in _OPTIONAL_NOTIFICATION_COLUMNS}
        if stripped == payload:
            raise
        logger.warning("Notification insert failed with extra columns, retrying without them: %s", e)
        supabase.table("notifications").insert(stripped).execute()


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
    related_ids = [
        (r.get("related_user_id") or r.get("actor_id"))
        for r in rows
        if (r.get("related_user_id") or r.get("actor_id"))
    ]
    summaries = get_user_summaries(related_ids) if related_ids else {}
    for row in rows:
        rid = row.get("related_user_id") or row.get("actor_id")
        row["related_user"] = summaries.get(rid) if rid else None
        if row.get("related_user_id") is None and rid:
            row["related_user_id"] = rid

    # Warnings (#191): mark them, and say whether each one has been acknowledged.
    from app.services.warning_service import warning_states, WARNING_NOTIFICATION_TYPE
    states = warning_states([r.get("warning_id") for r in rows if r.get("type") == WARNING_NOTIFICATION_TYPE])
    for row in rows:
        is_warning = row.get("type") == WARNING_NOTIFICATION_TYPE
        state = states.get(row.get("warning_id")) if is_warning else None
        row["is_warning"] = is_warning
        row["warning_acknowledged"] = bool(state and state.get("acknowledged_at")) if is_warning else None
        row["warning_withdrawn"] = bool(state and state.get("withdrawn_at")) if is_warning else None

    return {
        "page": page,
        "limit": limit,
        "data": rows
    }


def delete_notifications_for(user_id: str, type_: str, related_user_id: str):
    """Delete a user's notifications of one type that relate to a given other user."""
    try:
        response = supabase.table("notifications") \
            .delete() \
            .eq("user_id", user_id) \
            .eq("type", type_) \
            .eq("related_user_id", related_user_id) \
            .execute()
        return response.data or []
    except Exception as e:
        if _is_missing_column_error(e, "related_user_id"):
            response = supabase.table("notifications") \
                .delete() \
                .eq("user_id", user_id) \
                .eq("type", type_) \
                .eq("actor_id", related_user_id) \
                .execute()
            return response.data or []
        raise


def delete_notifications_for_request(friend_request_id: int):
    """Delete the notifications linked to one friend request."""
    response = supabase.table("notifications") \
        .delete() \
        .eq("friend_request_id", friend_request_id) \
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
