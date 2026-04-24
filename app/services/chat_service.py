from fastapi import HTTPException, status
from app.db.supabase_client import supabase


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

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


def _enrich_message(msg: dict, event_id: str, organizer_id: str = None, profiles: dict = None) -> dict:
    """Add sender_name and sender_role to a message dict."""
    sid = msg.get("sender_id")
    if not sid:
        msg["sender_name"] = "System"
        msg["sender_role"] = "system"
        return msg

    # If not pre-fetched, look them up individually (used by send_message)
    if organizer_id is None:
        event_resp = (
            supabase.table("events")
            .select("created_by")
            .eq("id", event_id)
            .single()
            .execute()
        )
        organizer_id = event_resp.data.get("created_by") if event_resp.data else None

    if profiles is None:
        profile_resp = (
            supabase.table("profiles")
            .select("full_name")
            .eq("id", sid)
            .single()
            .execute()
        )
        full_name = (profile_resp.data or {}).get("full_name") or "Unknown"
    else:
        full_name = profiles.get(sid, "Unknown")

    msg["sender_name"] = full_name
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
        print(f"[chat_service] Failed to post system notification: {exc}")
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
    event_resp = (
        supabase.table("events")
        .select("created_by")
        .eq("id", event_id)
        .single()
        .execute()
    )
    organizer_id = event_resp.data.get("created_by") if event_resp.data else None

    # Batch fetch all sender profiles
    sender_ids = list({m["sender_id"] for m in messages if m.get("sender_id")})
    profiles = {}
    if sender_ids:
        profiles_resp = (
            supabase.table("profiles")
            .select("id, full_name")
            .in_("id", sender_ids)
            .execute()
        )
        profiles = {p["id"]: p.get("full_name") or "Unknown" for p in (profiles_resp.data or [])}

    for msg in messages:
        _enrich_message(msg, event_id, organizer_id=organizer_id, profiles=profiles)

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

    return response.data[0]


def delete_message(user_id: str, message_id: int) -> dict:
    message = _get_message_or_404(message_id)

    if message["sender_id"] != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only delete your own messages")

    supabase.table("event_chats").delete().eq("id", message_id).execute()

    return {"message": "Chat message deleted successfully"}
