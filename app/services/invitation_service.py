"""Event invitations (ticket #186).

Removing invitations when the invited user joins, when the event is cancelled and
when a friendship ends is done by database triggers (see the migration
20261012120000_event_invitations.sql). Deleting an invitation also deletes its
notification (notifications.invitation_id ... on delete cascade).
Invitations to events that have started are hidden here and cleaned up on read.
"""
import logging
from datetime import datetime, timezone

from fastapi import HTTPException

from app.db.supabase_client import supabase
from app.services.event_service import _parse_start
from app.services.friendship_service import (
    _find_friendship,
    _is_unique_violation,
    _norm,
    _page,
    _uuid,
)
from app.services.profile_service import (
    USER_SUMMARY_COLUMNS,
    build_user_summary,
    get_user_summaries,
    get_username,
)
from app.utils.query_safety import like_contains

logger = logging.getLogger(__name__)

EVENT_INVITATION = "event_invitation"
DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 50
EVENT_COLUMNS = "id, title, start_datetime, status, created_by"

# Table created by #184 (blocking). Confirm the table and column names with whoever builds #184.
BLOCKS_TABLE = "user_blocks"

CAN_INVITE = "can_invite"
INVITED = "invited"
ATTENDING = "attending"
UNAVAILABLE = "unavailable"


def invitation_error(status_code: int, code: str, message: str) -> HTTPException:
    """Build an HTTPException with a structured invitation error detail."""
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


# ---------- helpers ----------

def _is_upcoming(event: dict) -> bool:
    """An event is upcoming when it is not cancelled and has not started yet."""
    if event.get("status") == "cancelled":
        return False
    start = _parse_start(event.get("start_datetime"))
    return start is not None and start > datetime.now(timezone.utc)


def _single(embed):
    """Return an embedded row as one dict, or None, whatever shape PostgREST used."""
    if isinstance(embed, list):
        embed = embed[0] if embed else None
    return embed if isinstance(embed, dict) else None


def _load_upcoming_event(event_id: str) -> dict:
    """Load an event, raising 404 if it does not exist and 400 if it is not upcoming."""
    try:
        event_id = _uuid(event_id)
    except ValueError:
        raise invitation_error(404, "event_not_found", "Event not found.")

    resp = supabase.table("events").select(EVENT_COLUMNS).eq("id", event_id).limit(1).execute()
    if not resp.data:
        raise invitation_error(404, "event_not_found", "Event not found.")

    event = resp.data[0]
    if not _is_upcoming(event):
        raise invitation_error(400, "event_not_upcoming",
                               "You can only invite friends to an upcoming event.")
    return event


def _attending_ids(event: dict, user_ids: list) -> set:
    """Return which of user_ids attend the event. The organizer always attends."""
    if not user_ids:
        return set()
    resp = (
        supabase.table("event_participants")
        .select("user_id")
        .eq("event_id", event["id"])
        .in_("user_id", list(user_ids))
        .execute()
    )
    attending = {_norm(row["user_id"]) for row in resp.data or []}
    organizer = event.get("created_by")
    if organizer and _norm(organizer) in {_norm(uid) for uid in user_ids}:
        attending.add(_norm(organizer))
    return attending


def _require_member(event: dict, user_id: str) -> None:
    """Only the organizer and the participants of an event may invite to it."""
    if _norm(user_id) not in _attending_ids(event, [user_id]):
        raise invitation_error(403, "not_event_member",
                               "Only the organizer and the participants of this event can invite friends to it.")


def _friend_ids(user_id: str) -> list:
    """Return the ids of all of the user's friends."""
    uid = _uuid(user_id)
    resp = (
        supabase.table("friendships")
        .select("user_id, friend_id")
        .or_(f"user_id.eq.{uid},friend_id.eq.{uid}")
        .execute()
    )
    return [
        row["friend_id"] if _norm(row["user_id"]) == _norm(uid) else row["user_id"]
        for row in resp.data or []
    ]


def _is_missing_table(exc: Exception) -> bool:
    text = str(exc)
    return getattr(exc, "code", None) in ("PGRST205", "42P01") or "PGRST205" in text or "42P01" in text


def _blocked_ids(user_id: str, other_ids: list) -> set:
    """Return which of other_ids were blocked by user_id or have blocked user_id."""
    others = [_uuid(other) for other in other_ids]
    if not others:
        return set()
    uid = _uuid(user_id)
    listed = ",".join(others)
    try:
        resp = (
            supabase.table(BLOCKS_TABLE)
            .select("blocker_id, blocked_id")
            .or_(f"and(blocker_id.eq.{uid},blocked_id.in.({listed})),"
                 f"and(blocked_id.eq.{uid},blocker_id.in.({listed}))")
            .execute()
        )
    except Exception as exc:
        if _is_missing_table(exc):
            # #184 has not created the blocks table yet, so nobody can have blocked anyone.
            logger.warning("Blocks table '%s' not found; treating nobody as blocked.", BLOCKS_TABLE)
            return set()
        raise

    blocked = set()
    for row in resp.data or []:
        other = row["blocked_id"] if _norm(row["blocker_id"]) == _norm(uid) else row["blocker_id"]
        blocked.add(_norm(other))
    return blocked


def _invited_by(inviter_id: str, event_id: str, user_ids: list) -> set:
    """Return which of user_ids already have an invitation from inviter_id to the event."""
    if not user_ids:
        return set()
    resp = (
        supabase.table("event_invitations")
        .select("invitee_id")
        .eq("event_id", event_id)
        .eq("inviter_id", inviter_id)
        .in_("invitee_id", list(user_ids))
        .execute()
    )
    return {_norm(row["invitee_id"]) for row in resp.data or []}


def _event_date(value) -> str:
    start = _parse_start(value)
    return start.strftime("%d %b %Y") if start else ""


def _notify_invitee(invitation: dict, event: dict) -> None:
    """Notify the invited user. Never fails the invitation itself."""
    title = event.get("title") or "an event"
    date = _event_date(event.get("start_datetime"))
    message = f"{get_username(invitation['inviter_id'])} invited you to '{title}'"
    if date:
        message += f" on {date}"
    try:
        supabase.table("notifications").insert({
            "user_id": invitation["invitee_id"],
            "event_id": invitation["event_id"],
            "type": EVENT_INVITATION,
            "message": message,
            "is_read": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "related_user_id": invitation["inviter_id"],
            "invitation_id": invitation["id"],
        }).execute()
    except Exception:
        logger.error("Failed to create invitation notification: invitation_id=%s",
                     invitation["id"], exc_info=True)


def _purge_stale_invitations(user_id: str) -> None:
    """Delete the user's invitations to events that have started or were cancelled."""
    resp = (
        supabase.table("event_invitations")
        .select("id, events(start_datetime, status)")
        .eq("invitee_id", user_id)
        .execute()
    )
    stale = [row["id"] for row in resp.data or [] if not _is_upcoming(_single(row.get("events")) or {})]
    if stale:
        supabase.table("event_invitations").delete().in_("id", stale).execute()


# ---------- public functions ----------

def invite_friend(inviter_id: str, event_id: str, invitee_id: str) -> dict:
    """Invite one friend to an upcoming event the inviter organizes or joined."""
    if _norm(inviter_id) == _norm(invitee_id):
        raise invitation_error(400, "cannot_invite_self", "You cannot invite yourself.")

    event = _load_upcoming_event(event_id)
    _require_member(event, inviter_id)

    if not _find_friendship(inviter_id, invitee_id):
        raise invitation_error(403, "not_friends", "You can only invite your friends.")

    if _norm(invitee_id) in _attending_ids(event, [invitee_id]):
        raise invitation_error(409, "already_attending", "This friend already attends the event.")

    organizer = event.get("created_by")
    if organizer and _norm(invitee_id) in _blocked_ids(organizer, [invitee_id]):
        # Do not say why: the inviter must not learn about the block.
        raise invitation_error(403, "cannot_invite", "This friend cannot be invited.")

    try:
        resp = (
            supabase.table("event_invitations")
            .insert({"event_id": event["id"], "inviter_id": inviter_id, "invitee_id": invitee_id})
            .execute()
        )
    except Exception as exc:
        if _is_unique_violation(exc):
            raise invitation_error(409, "already_invited", "You have already invited this friend.")
        raise

    if not resp.data:
        raise RuntimeError("invitation insert returned no row")
    invitation = resp.data[0]

    _notify_invitee(invitation, event)

    return {
        "invitation_id": invitation["id"],
        "event_id": str(invitation["event_id"]),
        "created_at": invitation["created_at"],
        "user": get_user_summaries([invitee_id])[invitee_id],
    }


def get_invitable_friends(user_id: str, event_id: str, search: str | None = None,
                          page: int = 1, limit: int = DEFAULT_PAGE_LIMIT) -> dict:
    """List the user's friends for the "Invite friends" window, with whether each can be invited."""
    event = _load_upcoming_event(event_id)
    _require_member(event, user_id)

    empty = {"page": page, "limit": limit, "has_more": False, "data": []}
    friend_ids = _friend_ids(user_id)
    if not friend_ids:
        return empty

    query = supabase.table("profiles").select(USER_SUMMARY_COLUMNS).in_("id", friend_ids)
    if search is not None:
        pattern = like_contains(search)
        if pattern:
            query = query.ilike("username", pattern)

    start = (page - 1) * limit
    resp = query.order("username").order("id").range(start, start + limit).execute()
    rows, has_more = _page(resp.data or [], limit)
    if not rows:
        return empty

    ids = [row["id"] for row in rows]
    attending = _attending_ids(event, ids)
    invited = _invited_by(user_id, event["id"], ids)
    blocked = _blocked_ids(event["created_by"], ids) if event.get("created_by") else set()

    data = []
    for row in rows:
        key = _norm(row["id"])
        if key in attending:
            status = ATTENDING
        elif key in invited:
            status = INVITED
        elif key in blocked:
            status = UNAVAILABLE
        else:
            status = CAN_INVITE
        data.append({"user": build_user_summary(row), "invite_status": status, "can_invite": status == CAN_INVITE})

    return {"page": page, "limit": limit, "has_more": has_more, "data": data}


def get_my_invitations(user_id: str, page: int = 1, limit: int = DEFAULT_PAGE_LIMIT) -> dict:
    """List the signed-in user's invitations, newest first, with their total number."""
    _purge_stale_invitations(user_id)

    start = (page - 1) * limit
    resp = (
        supabase.table("event_invitations")
        .select("id, event_id, inviter_id, created_at, events(id, title, start_datetime)", count="exact")
        .eq("invitee_id", user_id)
        .order("created_at", desc=True)
        .order("id", desc=True)
        .range(start, start + limit)
        .execute()
    )
    rows, has_more = _page(resp.data or [], limit)

    inviters = get_user_summaries([row["inviter_id"] for row in rows]) if rows else {}
    data = []
    for row in rows:
        event = _single(row.get("events")) or {}
        data.append({
            "invitation_id": row["id"],
            "created_at": row["created_at"],
            "inviter": inviters[row["inviter_id"]],
            "event": {
                "id": str(event.get("id") or row["event_id"]),
                "title": event.get("title"),
                "start_datetime": event.get("start_datetime"),
            },
        })

    return {"page": page, "limit": limit, "has_more": has_more, "total": resp.count or 0, "data": data}


def dismiss_invitation(user_id: str, invitation_id: int) -> dict:
    """Delete an invitation the user received. Its notification is deleted with it."""
    resp = (
        supabase.table("event_invitations")
        .delete()
        .eq("id", invitation_id)
        .eq("invitee_id", user_id)
        .execute()
    )
    if not resp.data:
        raise invitation_error(404, "invitation_not_found", "Invitation not found.")
    return {"message": "Invitation dismissed"}


def get_invitation_summary(user_id: str, event: dict) -> dict:
    """For an event's details: is the user invited, who invited them first, how many others did."""
    summary = {"invited": False, "invited_by": None, "other_inviters_count": 0}
    if not _is_upcoming(event):
        return summary

    resp = (
        supabase.table("event_invitations")
        .select("inviter_id, created_at")
        .eq("event_id", event["id"])
        .eq("invitee_id", user_id)
        .order("created_at")
        .order("id")
        .execute()
    )
    rows = resp.data or []
    if not rows:
        return summary

    first = rows[0]["inviter_id"]
    return {
        "invited": True,
        "invited_by": get_user_summaries([first])[first],
        "other_inviters_count": len(rows) - 1,
    }


def remove_invitations_for_block(user_a: str, user_b: str) -> None:
    """Called by the blocking code (#184) when one user blocks the other.

    Removes the invitations either user received to events the other organizes,
    and the invitations between the two of them, with their notifications.
    """
    supabase.rpc("remove_invitations_for_block", {"user_a": _uuid(user_a), "user_b": _uuid(user_b)}).execute()