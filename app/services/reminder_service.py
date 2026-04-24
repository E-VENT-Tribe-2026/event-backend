import logging
from datetime import datetime, timezone, timedelta
from app.db.supabase_client import supabase
from app.services.email_service import send_email, build_reminder_email
from app.services.notification_service import create_notification

logger = logging.getLogger(__name__)

REMINDER_HOURS = 2


def _get_user_email(user_id: str) -> str | None:
    """Fetch a user's email via Supabase Auth admin REST API."""
    import httpx
    from app.core.config import settings
    try:
        url = f"{settings.SUPABASE_URL}/auth/v1/admin/users/{user_id}"
        headers = {
            "apikey": settings.SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
        }
        resp = httpx.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            return resp.json().get("email")
        logger.warning(f"Auth admin returned {resp.status_code} for user {user_id}: {resp.text}")
        return None
    except Exception as e:
        logger.warning(f"Could not fetch email for user {user_id}: {e}")
        return None


def _get_upcoming_events() -> list[dict]:
    """Return active events whose start_datetime falls in the next 2–3 hours."""
    now = datetime.now(timezone.utc)
    window_start = now + timedelta(hours=REMINDER_HOURS)
    window_end = window_start + timedelta(hours=1)

    response = (
        supabase.table("events")
        .select("*")
        .eq("status", "active")
        .gte("start_datetime", window_start.isoformat())
        .lte("start_datetime", window_end.isoformat())
        .execute()
    )
    return response.data or []


def _get_participant_user_ids(event_id: str) -> list[str]:
    response = (
        supabase.table("event_participants")
        .select("user_id")
        .eq("event_id", event_id)
        .execute()
    )
    return [row["user_id"] for row in (response.data or [])]


def _get_saved_event_user_ids(event_id: str) -> list[str]:
    response = (
        supabase.table("saved_events")
        .select("user_id")
        .eq("event_id", event_id)
        .execute()
    )
    return [row["user_id"] for row in (response.data or [])]


def _already_reminded(user_id: str, event_id: str) -> bool:
    """Check the notifications table to avoid sending duplicate reminders."""
    response = (
        supabase.table("notifications")
        .select("id")
        .eq("user_id", user_id)
        .eq("event_id", event_id)
        .eq("type", "reminder")
        .execute()
    )
    return bool(response.data)


def send_event_reminders():
    """
    Scheduled job: find events starting in ~12 hours and email all
    attending/saved users who haven't been reminded yet.
    Failures are isolated per-user and do not affect the rest of the job.
    """
    logger.info("Running event reminder job...")

    try:
        events = _get_upcoming_events()
    except Exception as e:
        logger.error(f"Failed to fetch upcoming events: {e}")
        return

    if not events:
        logger.info("No upcoming events in reminder window.")
        return

    for event in events:
        event_id = event["id"]
        title = event.get("title", "Upcoming Event")

        # Union participants + saved-event users so no one is missed
        participant_ids = set(_get_participant_user_ids(event_id))
        saved_ids = set(_get_saved_event_user_ids(event_id))
        all_user_ids = participant_ids | saved_ids

        if not all_user_ids:
            continue

        subject, plain, html = build_reminder_email(event)
        sent, failed = 0, 0

        for user_id in all_user_ids:
            if _already_reminded(user_id, event_id):
                continue

            email = _get_user_email(user_id)
            if not email:
                logger.warning(f"No email for user {user_id}, skipping.")
                continue

            try:
                send_email(email, subject, plain, html)
                # Also create an in-app notification (dedup handled inside)
                create_notification(
                    user_id=user_id,
                    event_id=event_id,
                    type_="reminder",
                    message=f"Reminder: \"{title}\" starts in {REMINDER_HOURS} hours.",                )
                sent += 1
            except Exception as e:
                logger.error(f"Reminder failed for user {user_id}, event {event_id}: {e}")
                failed += 1

        logger.info(f"Event '{title}' ({event_id}): {sent} sent, {failed} failed.")