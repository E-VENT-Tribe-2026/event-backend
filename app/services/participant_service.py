from fastapi import HTTPException
from app.db.supabase_client import supabase


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_event(event_id: str) -> dict:
    """Fetch event row or raise 404."""
    response = (
        supabase.table("events")
        .select("id, created_by")
        .eq("id", event_id)
        .single()
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=404, detail="Event not found")
    return response.data


def _is_participant(user_id: str, event_id: str) -> bool:
    """Return True if the user has an active participation row."""
    response = (
        supabase.table("event_participants")
        .select("user_id")
        .eq("user_id", user_id)
        .eq("event_id", event_id)
        .execute()
    )
    return bool(response.data)


# ---------------------------------------------------------------------------
# Join / Leave
# ---------------------------------------------------------------------------

def join_event(user_id: str, event_id: str):
    event = _get_event(event_id)

    if event["created_by"] == user_id:
        raise HTTPException(
            status_code=400,
            detail="Event organizers cannot join their own event.",
        )

    if _is_participant(user_id, event_id):
        raise HTTPException(status_code=400, detail="User already joined event")

    response = (
        supabase.table("event_participants")
        .insert({
            "user_id": user_id,
            "event_id": event_id,
            "status": "going",
        })
        .execute()
    )
    return response.data


def leave_event(user_id: str, event_id: str):
    supabase.table("event_participants").delete().eq("user_id", user_id).eq("event_id", event_id).execute()
    return {"message": "Left event successfully"}


# ---------------------------------------------------------------------------
# Get attendees  (access-controlled)
# ---------------------------------------------------------------------------

def get_event_attendees(event_id: str, requesting_user_id: str) -> dict:
    """
    Access rules:
      - Organizer (created_by)  → full attendee list
      - Joined participant      → full attendee list
      - Everyone else           → attendee count only
    """
    event = _get_event(event_id)
    is_organizer = event["created_by"] == requesting_user_id
    is_joined = _is_participant(requesting_user_id, event_id)

    # Always fetch full list — needed for count regardless of access level
    response = (
        supabase.table("event_participants")
        .select("user_id, status, created_at, profiles(id, full_name, avatar_url)")
        .eq("event_id", event_id)
        .execute()
    )
    participants = response.data or []
    count = len(participants)

    if is_organizer or is_joined:
        return {
            "event_id": event_id,
            "attendee_count": count,
            "attendees": participants,
        }

    # Restricted view — count only
    return {
        "event_id": event_id,
        "attendee_count": count,
        "attendees": None,
        "detail": "Join the event to see the full attendee list.",
    }


# ---------------------------------------------------------------------------
# Remove participant  (organizer only)
# ---------------------------------------------------------------------------

def remove_participant(organizer_id: str, event_id: str, target_user_id: str) -> dict:
    """
    Only the event organizer (created_by) can remove a participant.
    Deleting the row revokes the participant's event access immediately.
    """
    event = _get_event(event_id)

    if event["created_by"] != organizer_id:
        raise HTTPException(
            status_code=403,
            detail="Only the event organizer can remove participants.",
        )

    if organizer_id == target_user_id:
        raise HTTPException(
            status_code=400,
            detail="Organizers cannot remove themselves. Use delete event instead.",
        )

    if not _is_participant(target_user_id, event_id):
        raise HTTPException(
            status_code=404,
            detail="Participant not found in this event.",
        )

    supabase.table("event_participants").delete().eq("user_id", target_user_id).eq("event_id", event_id).execute()

    return {
        "message": "Participant removed successfully.",
        "event_id": event_id,
        "removed_user_id": target_user_id,
    }