from fastapi import HTTPException, status
from app.db.supabase_client import supabase


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

def _get_message_or_404(message_id: int) -> dict:
    """Fetch a single chat message; raise 404 if not found."""
    response = (
        supabase.table("event_chats")
        .select("*")
        .eq("id", message_id)
        .single()
        .execute()
    )
    if not response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat message not found"
        )
    return response.data


def _assert_participant(user_id: str, event_id: str) -> None:
    """Raise 403 if the user is not a participant of the event."""
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


# ────────────────────────────────────────────────────────────────────────────
# CRUD operations
# ────────────────────────────────────────────────────────────────────────────

def send_message(user_id: str, event_id: str, content: str) -> dict:
    """
    Create a new chat message in an event.
    The sender must be a participant of the event.
    """
    _assert_participant(user_id, event_id)

    if not content or not content.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message content cannot be empty"
        )

    payload = {
        "event_id": event_id,
        "sender_id": user_id,
        "content": content.strip(),
    }

    response = supabase.table("event_chats").insert(payload).execute()

    if not response.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to send message"
        )

    return response.data[0]


def get_event_messages(
    user_id: str,
    event_id: str,
    page: int = 1,
    limit: int = 50,
) -> dict:
    """
    Fetch paginated chat messages for an event (oldest-first within page).
    The caller must be a participant of the event.
    """
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

    return {
        "event_id": event_id,
        "page": page,
        "limit": limit,
        "data": response.data or [],
    }


def update_message(user_id: str, message_id: int, new_content: str) -> dict:
    """
    Edit the content of an existing chat message.
    Only the original sender can edit their own message.
    """
    message = _get_message_or_404(message_id)

    if message["sender_id"] != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only edit your own messages"
        )

    if not new_content or not new_content.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Updated content cannot be empty"
        )

    response = (
        supabase.table("event_chats")
        .update({"content": new_content.strip()})
        .eq("id", message_id)
        .execute()
    )

    if not response.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to update message"
        )

    return response.data[0]


def delete_message(user_id: str, message_id: int) -> dict:
    """
    Delete a chat message.
    Only the original sender can delete their own message.
    """
    message = _get_message_or_404(message_id)

    if message["sender_id"] != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own messages"
        )

    supabase.table("event_chats").delete().eq("id", message_id).execute()

    return {"message": "Chat message deleted successfully"}
