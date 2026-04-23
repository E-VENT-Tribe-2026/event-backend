import logging
from fastapi import HTTPException
from app.db.supabase_client import supabase
from app.services.notification_service import create_notification
from app.services.event_service import get_event

logger = logging.getLogger(__name__)


def _get_user_email(user_id: str) -> str | None:
    try:
        resp = supabase.auth.admin.get_user_by_id(user_id)
        return resp.user.email if resp and resp.user else None
    except Exception as e:
        logger.warning(f"Could not fetch email for user {user_id}: {e}")
        return None


def join_event(user_id: str, event_id: str):
    from app.services.email_service import send_email, build_join_confirmation_email

    event = get_event(event_id)
    title = event.get("title", "Event")

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
        .insert({"user_id": user_id, "event_id": event_id, "status": "going"})
        .execute()
    )

    # Notify organizer
    create_notification(
        event["created_by"],
        event_id,
        "user_joined",
        f"Someone joined your event '{title}'"
    )

    # Notify participant
    create_notification(
        user_id,
        event_id,
        "joined_event",
        f"You have successfully joined '{title}'"
    )

    # Email participant only
    try:
        email = _get_user_email(user_id)
        if email:
            subject, plain, html = build_join_confirmation_email(event)
            send_email(email, subject, plain, html)
    except Exception as e:
        logger.error(f"Join confirmation email failed for user {user_id}: {e}")

    return response.data


def leave_event(user_id: str, event_id: str):
    event = get_event(event_id)
    title = event.get("title", "Event")

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
        f"Someone left your event '{title}'"
    )

    return {"message": "Left event successfully"}


def remove_participant(organizer_id: str, event_id: str, participant_id: str):
    from app.services.email_service import send_email, build_removed_from_event_email

    event = get_event(event_id)

    if event["created_by"] != organizer_id:
        raise HTTPException(status_code=403, detail="Only the event owner can remove participants")

    supabase.table("event_participants") \
        .delete() \
        .eq("event_id", event_id) \
        .eq("user_id", participant_id) \
        .execute()

    title = event.get("title", "Event")

    # Notify the removed participant
    create_notification(
        participant_id,
        event_id,
        "removed_from_event",
        f"You have been removed from '{title}' by the organizer."
    )

    # Email the removed participant
    try:
        email = _get_user_email(participant_id)
        if email:
            subject, plain, html = build_removed_from_event_email(event)
            send_email(email, subject, plain, html)
    except Exception as e:
        logger.error(f"Removal email failed for user {participant_id}: {e}")

    return {"message": "Participant removed"}


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
