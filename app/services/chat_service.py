from fastapi import HTTPException, status
from app.db.supabase_client import supabase
from app.services.profile_service import get_user_summaries, build_user_summary
from app.services.removed_content import (
    MESSAGE_REMOVED_CONTENT,
    assert_event_not_removed,
    message_removed_error,
)
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
    if not result.data and _get_organizer_id(event_id) != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be a participant of this event to access its chat"
        )


def _assert_event_not_cancelled(event_id: str) -> None:
    try:
        event_resp = (
            supabase.table("events")
            .select("status")
            .eq("id", event_id)
            .single()
            .execute()
        )
        if event_resp.data and event_resp.data.get("status") == "cancelled":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Chat is read-only for cancelled events"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Event status lookup failed for event {event_id}: {e}")


def _people_for_message(msg: dict, senders: dict | None) -> dict:
    needed = [uid for uid in (msg.get("sender_id"), msg.get("removed_by")) if uid]
    if not needed:
        return senders or {}
    missing = needed if senders is None else [uid for uid in needed if uid not in senders]
    if not missing:
        return senders
    return {**(senders or {}), **get_user_summaries(missing)}


def _enrich_message(msg: dict, event_id: str, organizer_id=_ORGANIZER_UNSET, senders: dict = None) -> dict:
    """Add sender, sender_name and sender_role to a message dict.

    A message an administrator removed (#236) keeps its sender; users see a placeholder
    instead of the original text, plus the administrator who removed it. The original
    stays in the database. Works on a copy so the stored row is not rewritten.
    """
    msg = dict(msg)
    msg["is_removed"] = bool(msg.get("removed_at"))
    msg.setdefault("removed_at", None)
    people = _people_for_message(msg, senders)

    remover_id = msg.get("removed_by") if msg["is_removed"] else None
    if remover_id:
        remover = people.get(remover_id) or build_user_summary(None, remover_id)
        msg["removed_by"] = dict(remover)
        msg["removed_by_name"] = (
            msg["removed_by"].get("full_name") or msg["removed_by"].get("display_name") or "Unknown"
        )
    else:
        msg["removed_by"] = None
        msg["removed_by_name"] = None

    if msg["is_removed"]:
        msg["content"] = MESSAGE_REMOVED_CONTENT

    sid = msg.get("sender_id")
    if not sid:
        msg["sender"] = None
        msg["sender_name"] = "System"
        msg["sender_role"] = "system"
        return msg

    # If not pre-fetched, look them up individually (used by send_message and update_message)
    if organizer_id is _ORGANIZER_UNSET:
        organizer_id = _get_organizer_id(event_id)

    # Defensive fallback only: get_user_summaries already returns a stub for every requested id
    sender = people.get(sid) or build_user_summary(None, sid)

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
    assert_event_not_removed(event_id)
    _assert_event_not_cancelled(event_id)

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
    assert_event_not_removed(event_id)

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

    # Batch fetch sender and removing-administrator summaries in a single query
    people_ids = list({
        uid
        for m in messages
        for uid in (m.get("sender_id"), m.get("removed_by"))
        if uid
    })
    senders = get_user_summaries(people_ids) if people_ids else {}

    messages = [
        _enrich_message(msg, event_id, organizer_id=organizer_id, senders=senders)
        for msg in messages
    ]

    return {"event_id": event_id, "page": page, "limit": limit, "data": messages}


def update_message(user_id: str, message_id: int, new_content: str) -> dict:
    message = _get_message_or_404(message_id)
    assert_event_not_removed(message["event_id"])
    _assert_event_not_cancelled(message["event_id"])

    if message["sender_id"] != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only edit your own messages")
    if message.get("removed_at"):
        raise message_removed_error()

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
    assert_event_not_removed(message["event_id"])
    _assert_event_not_cancelled(message["event_id"])

    if message["sender_id"] != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only delete your own messages")
    if message.get("removed_at"):
        raise message_removed_error()

    supabase.table("event_chats").delete().eq("id", message_id).execute()

    return {"message": "Chat message deleted successfully"}
