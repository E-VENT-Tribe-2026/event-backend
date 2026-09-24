from fastapi import HTTPException, status
from app.db.supabase_client import supabase
from app.services.profile_service import get_user_summaries, build_user_summary
import logging

logger = logging.getLogger(__name__)

# Sentinel to distinguish "organizer id not yet looked up" from "looked up
# but the event/organizer could not be resolved" (which is a legitimate None).
_ORGANIZER_UNSET = object()


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

def _get_organizer_id(event_id: str) -> str | None:
    """Return the event's organizer id, or None when it cannot be looked up."""
    try:
        event_resp = (
            supabase.table("events")
            .select("created_by")
            .eq("id", event_id)
            .single()
            .execute()
        )
        return event_resp.data.get("created_by") if event_resp.data else None
    except Exception as e:
        logger.error(f"Organizer lookup failed for event {event_id}: {e}", exc_info=True)
        return None


def _get_message_or_404(message_id: int) -> dict:
    response = (
        supabase.table("event_chats")
        .select("*")
        .eq("id", message_id)
        .single()
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat message not found")
    return response.data


def _assert_participant(user_id: str, event_id: str) -> None:
    result = (
        supabase.table("event_participants")
        .select("user_id")
        .eq("event_id", event_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be a participant of this event to access its chat"
        )


def _enrich_message(msg: dict, event_id: str, organizer_id=_ORGANIZER_UNSET, senders: dict = None) -> dict:
    """Add sender, sender_name and sender_role to a message dict."""
    sid = msg.get("sender_id")
    if not sid:
        msg["sender"] = None
        msg["sender_name"] = "System"
        msg["sender_role"] = "system"
        return msg

    # If not pre-fetched, look them up individually (used by send_message and update_message)
    if organizer_id is _ORGANIZER_UNSET:
        organizer_id = _get_organizer_id(event_id)

    if senders is None:
        senders = get_user_summaries([sid])

    # Defensive fallback only: get_user_summaries already returns a stub for every requested id
    sender = senders.get(sid) or build_user_summary(None, sid)

    msg["sender"] = dict(sender)
    msg["sender_name"] = msg["sender"].get("full_name") or "Unknown"
    msg["sender_role"] = "organizer" if sid == organizer_id else "participant"
    return msg


# ────────────────────────────────────────────────────────────────────────────
# System notifications
# ────────────────────────────────────────────────────────────────────────────

def post_system_notification(event_id: str, content: str) -> dict | None:
    try:
        payload = {"event_id": event_id, "content": content, "type": "notification", "sender_id": None}
        response = supabase.table("event_chats").insert(payload).execute()
        return response.data[0] if response.data else None
    except Exception as exc:
        logger.error(f"Failed to post system notification for event {event_id}: {exc}")
        return None


# ────────────────────────────────────────────────────────────────────────────
# CRUD
# ────────────────────────────────────────────────────────────────────────────

def send_message(user_id: str, event_id: str, content: str) -> dict:
    _assert_participant(user_id, event_id)

    if not content or not content.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Message content cannot be empty")

    response = supabase.table("event_chats").insert({
        "event_id": event_id,
        "sender_id": user_id,
        "content": content.strip(),
    }).execute()

    if not response.data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to send message")

    return _enrich_message(response.data[0], event_id)


def get_event_messages(user_id: str, event_id: str, page: int = 1, limit: int = 50) -> dict:
    _assert_participant(user_id, event_id)

    start = (page - 1) * limit
    end = start + limit - 1

    response = (
        supabase.table("event_chats")
        .select("*")
        .eq("event_id", event_id)
        .order("created_at", desc=False)
        .range(start, end)
        .execute()
    )

    messages = response.data or []

    if not messages:
        return {"event_id": event_id, "page": page, "limit": limit, "data": []}

    # Fetch organizer once
    organizer_id = _get_organizer_id(event_id)

    # Batch fetch all sender summaries in a single query
    sender_ids = list({m["sender_id"] for m in messages if m.get("sender_id")})
    senders = get_user_summaries(sender_ids) if sender_ids else {}

    for msg in messages:
        _enrich_message(msg, event_id, organizer_id=organizer_id, senders=senders)

    return {"event_id": event_id, "page": page, "limit": limit, "data": messages}


def update_message(user_id: str, message_id: int, new_content: str) -> dict:
    message = _get_message_or_404(message_id)

    if message["sender_id"] != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only edit your own messages")

    if not new_content or not new_content.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Updated content cannot be empty")

    response = (
        supabase.table("event_chats")
        .update({"content": new_content.strip()})
        .eq("id", message_id)
        .execute()
    )

    if not response.data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to update message")

    return _enrich_message(response.data[0], message["event_id"])


def delete_message(user_id: str, message_id: int) -> dict:
    message = _get_message_or_404(message_id)

    if message["sender_id"] != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only delete your own messages")

    supabase.table("event_chats").delete().eq("id", message_id).execute()

    return {"message": "Chat message deleted successfully"}
