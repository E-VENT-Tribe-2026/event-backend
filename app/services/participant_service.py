import logging
from fastapi import HTTPException
from app.db.supabase_client import supabase
from app.services.notification_service import create_notification
from app.services.event_service import get_event
from app.services.chat_service import post_system_notification
from app.services.profile_service import get_username, build_user_summary
from app.services.friendship_service import get_friend_ids
from app.core.dependencies import require_admin

logger = logging.getLogger(__name__)


def _get_user_email(user_id: str) -> str | None:
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


def _join_side_effects(user_id: str, event_id: str, event: dict):
    """Notifications, chat message, and email — runs in background after response is sent."""
    from app.services.email_service import send_email, build_join_confirmation_email

    title = event.get("title", "Event")
    username = get_username(user_id)

    try:
        post_system_notification(event_id, f"👋 {username} has joined this chat")
    except Exception as e:
        logger.error(f"System chat notification failed on join: {e}")

    try:
        create_notification(event["created_by"], event_id, "user_joined",
                            f"{username} joined your event '{title}'")
        create_notification(user_id, event_id, "joined_event",
                            f"You have joined '{title}'")
    except Exception as e:
        logger.error(f"Notification failed on join: {e}")

    try:
        email = _get_user_email(user_id)
        if email:
            subject, plain, html = build_join_confirmation_email(event)
            send_email(email, subject, plain, html)
    except Exception as e:
        logger.error(f"Join confirmation email failed for user {user_id}: {e}")


def join_event(user_id: str, event_id: str):
    event = get_event(event_id)

    if event.get("status") == "cancelled":
        raise HTTPException(status_code=400, detail="Cannot join a cancelled event")

    existing = (
        supabase.table("event_participants")
        .select("user_id")
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

    # Return data and event so the route can schedule side effects in background
    return response.data, event


def leave_event(user_id: str, event_id: str):
    event = get_event(event_id)

    if event.get("status") == "cancelled":
        raise HTTPException(status_code=400, detail="Cannot leave a cancelled event")

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

    return {"message": "Left event successfully"}, event


def _leave_side_effects(user_id: str, event_id: str, event: dict):
    """Runs in background after leave response is sent."""
    from app.services.email_service import send_email, build_leave_event_email

    title = event.get("title", "Event")
    try:
        username = get_username(user_id)
        post_system_notification(event_id, f"👋 {username} has left this chat")
        create_notification(event["created_by"], event_id, "user_left",
                            f"{username} left your event '{title}'")
        create_notification(user_id, event_id, "left_event",
                            f"You have left '{title}'")
    except Exception as e:
        logger.error(f"Leave notifications failed: {e}")

    try:
        email = _get_user_email(user_id)
        if email:
            subject, plain, html = build_leave_event_email(event)
            send_email(email, subject, plain, html)
    except Exception as e:
        logger.error(f"Leave confirmation email failed for user {user_id}: {e}")


def remove_participant(organizer_id: str, event_id: str, participant_id: str):
    event = get_event(event_id)

    if event.get("status") == "cancelled":
        raise HTTPException(status_code=400, detail="Cannot remove participants from a cancelled event")

    if event["created_by"] != organizer_id:
        raise HTTPException(status_code=403, detail="Only the event owner can remove participants")

    supabase.table("event_participants") \
        .delete() \
        .eq("event_id", event_id) \
        .eq("user_id", participant_id) \
        .execute()

    return {"message": "Participant removed"}, event


def _remove_side_effects(organizer_id: str, event_id: str, participant_id: str, event: dict):
    """Runs in background after remove response is sent."""
    from app.services.email_service import send_email, build_removed_from_event_email

    title = event.get("title", "Event")
    organizer_username = get_username(organizer_id)

    try:
        create_notification(participant_id, event_id, "removed_from_event",
                            f"You have been removed from '{title}' by {organizer_username}.")
    except Exception as e:
        logger.error(f"Remove notification failed: {e}")

    try:
        email = _get_user_email(participant_id)
        if email:
            subject, plain, html = build_removed_from_event_email(event)
            send_email(email, subject, plain, html)
    except Exception as e:
        logger.error(f"Removal email failed for user {participant_id}: {e}")


def _trim_profile(profile: dict) -> dict:
    return {
        "full_name": profile.get("full_name"),
        "avatar_url": profile.get("avatar_url"),
    }


def _single_profile(embed):
    """Return the embedded profile as one dict, or None, whatever shape PostgREST used."""
    if isinstance(embed, list):
        embed = embed[0] if embed else None
    return embed if isinstance(embed, dict) else None


def _norm(value) -> str:
    return str(value).strip().lower()


_PARTICIPANT_SELECT = "user_id, status, profiles(username, full_name, avatar_url, avatar_kind, icon_id)"


def _participant_row(row: dict) -> dict:
    """Shape one event_participants row; profiles keeps its existing {full_name, avatar_url} shape."""
    profile = _single_profile(row.get("profiles"))
    row["user"] = build_user_summary(profile, row.get("user_id"))
    row["profiles"] = _trim_profile(profile) if profile is not None else None
    return row


def get_event_participants(event_id: str, viewer_id: str | None = None):
    """Return an event's participants, each with a user summary.

    With viewer_id, every row also carries is_friend: whether that participant is a friend of the viewer.
    """
    response = (
        supabase.table("event_participants")
        .select(_PARTICIPANT_SELECT)
        .eq("event_id", event_id)
        .execute()
    )
    rows = [_participant_row(row) for row in (response.data or [])]
    if viewer_id is not None:
        friends = {_norm(fid) for fid in get_friend_ids(viewer_id)}
        for row in rows:
            row["is_friend"] = _norm(row.get("user_id")) in friends
    return rows


def is_administrator(user, credentials) -> bool:
    """Same rule as the admin panel: run require_admin; a refusal means not an administrator."""
    try:
        require_admin(credentials=credentials, user=user)
        return True
    except HTTPException:
        return False


def can_view_participants(event: dict, user, credentials) -> bool:
    """The participant list is for the organizer, the participants and administrators only."""
    if _norm(event.get("created_by")) == _norm(user.id):
        return True
    response = (
        supabase.table("event_participants")
        .select("user_id")
        .eq("event_id", event["id"])
        .eq("user_id", user.id)
        .execute()
    )
    if response.data:
        return True
    return is_administrator(user, credentials)


def get_participants_for_viewer(event_id: str, user, credentials):
    """The full participant list, marked with the viewer's friends. 403 unless the viewer may see it."""
    event = get_event(event_id)
    if not can_view_participants(event, user, credentials):
        raise HTTPException(
            status_code=403,
            detail="Only the organizer, the participants and administrators can see the participant list",
        )
    return get_event_participants(event_id, viewer_id=user.id)


def get_friends_attending(event_id: str, user_id: str):
    """The participants of an event who are friends of the user, in the participant row shape."""
    event = get_event(event_id)
    friend_ids = get_friend_ids(user_id)
    if not friend_ids:
        return []
    response = (
        supabase.table("event_participants")
        .select(_PARTICIPANT_SELECT)
        .eq("event_id", event_id)
        .in_("user_id", friend_ids)
        .execute()
    )
    rows = [_participant_row(row) for row in (response.data or [])]
    seen = {_norm(row["user_id"]) for row in rows}
    organizer = event.get("created_by")
    if organizer and _norm(organizer) in {_norm(f) for f in friend_ids} and _norm(organizer) not in seen:
        profiles = (
            supabase.table("profiles")
            .select("username, full_name, avatar_url, avatar_kind, icon_id")
            .eq("id", organizer)
            .execute()
        ).data
        rows.append(_participant_row({"user_id": organizer, "status": "going", "profiles": profiles}))
    for row in rows:
        row["is_friend"] = True
    return rows


def attach_friends_attending_count(events: list, user_id: str | None) -> list:
    """Add friends_attending_count (how many of the user's friends attend) to each event, in place.

    Never raises; if the lookup fails the count is 0.
    """
    items = [e for e in (events or []) if isinstance(e, dict) and e.get("id")]
    if not items or not user_id:
        return events
    counts: dict[str, set] = {}
    try:
        friend_ids = get_friend_ids(user_id)
        friends = {_norm(f) for f in friend_ids}
        if friends:
            response = (
                supabase.table("event_participants")
                .select("event_id, user_id")
                .in_("event_id", [e["id"] for e in items])
                .in_("user_id", friend_ids)
                .execute()
            )
            for row in response.data or []:
                counts.setdefault(row["event_id"], set()).add(_norm(row["user_id"]))
            for e in items:
                if e.get("created_by") and _norm(e["created_by"]) in friends:
                    counts.setdefault(e["id"], set()).add(_norm(e["created_by"]))
    except Exception as e:
        logger.error(f"Friends attending count failed for user {user_id}: {e}", exc_info=True)
    for e in items:
        e["friends_attending_count"] = len(counts.get(e["id"], ()))
    return events


def get_my_events(user_id: str):
    response = supabase.table("event_participants") \
        .select("event_id, events(*)") \
        .eq("user_id", user_id) \
        .execute()
    return response.data or []
