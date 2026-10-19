"""Who a user must not see, and which events that hides (ticket #184).

Kept free of other service imports so event, profile and friendship code can use it.
Table: user_blocks(blocker_id, blocked_id, created_at).

An event is hidden from a signed-in user when its organizer is someone they blocked or
someone who blocked them, unless the user is a participant of that event: events a user
had joined before the block stay visible, and events the other user only joined are never
hidden because only the organizer counts.
"""
import logging
import uuid

from app.db.supabase_client import supabase

logger = logging.getLogger(__name__)

BLOCKS_TABLE = "user_blocks"


def _norm(value) -> str:
    return str(value).strip().lower()


def _uuid(value) -> str:
    """Canonical form of a uuid; raises ValueError for anything else (keeps filters injection-safe)."""
    return str(uuid.UUID(str(value)))


def _valid(*ids) -> bool:
    """Real user ids are always uuids; anything else cannot be in user_blocks."""
    try:
        for value in ids:
            _uuid(value)
    except ValueError:
        return False
    return True


def get_blocked_by_ids(user_id: str) -> set:
    """Ids of the users who blocked user_id."""
    if not _valid(user_id):
        return set()
    resp = (
        supabase.table(BLOCKS_TABLE)
        .select("blocker_id")
        .eq("blocked_id", _uuid(user_id))
        .execute()
    )
    return {_norm(r["blocker_id"]) for r in resp.data or []}


def get_blocked_ids(user_id: str) -> set:
    """Ids of the users user_id blocked."""
    if not _valid(user_id):
        return set()
    resp = (
        supabase.table(BLOCKS_TABLE)
        .select("blocked_id")
        .eq("blocker_id", _uuid(user_id))
        .execute()
    )
    return {_norm(r["blocked_id"]) for r in resp.data or []}


def get_hidden_user_ids(user_id: str) -> set:
    """Ids of the users user_id blocked plus the users who blocked user_id."""
    if not _valid(user_id):
        return set()
    uid = _uuid(user_id)
    resp = (
        supabase.table(BLOCKS_TABLE)
        .select("blocker_id, blocked_id")
        .or_(f"blocker_id.eq.{uid},blocked_id.eq.{uid}")
        .execute()
    )
    hidden = set()
    for row in resp.data or []:
        other = row["blocked_id"] if _norm(row["blocker_id"]) == _norm(uid) else row["blocker_id"]
        hidden.add(_norm(other))
    return hidden


def has_blocked(blocker_id: str, blocked_id: str) -> bool:
    if not _valid(blocker_id, blocked_id):
        return False
    resp = (
        supabase.table(BLOCKS_TABLE)
        .select("blocker_id")
        .eq("blocker_id", _uuid(blocker_id))
        .eq("blocked_id", _uuid(blocked_id))
        .limit(1)
        .execute()
    )
    return bool(resp.data)


def _joined_event_ids(user_id: str, event_ids: list) -> set:
    """The subset of event_ids the user participates in."""
    if not event_ids:
        return set()
    resp = (
        supabase.table("event_participants")
        .select("event_id")
        .eq("user_id", user_id)
        .in_("event_id", event_ids)
        .execute()
    )
    return {str(r["event_id"]) for r in resp.data or []}


def _organizers(events: list) -> dict:
    """Map event id -> organizer id for events whose rows lack created_by (e.g. RPC rows)."""
    ids = [str(e["id"]) for e in events if "created_by" not in e and e.get("id")]
    if not ids:
        return {}
    resp = supabase.table("events").select("id, created_by").in_("id", ids).execute()
    return {str(r["id"]): r.get("created_by") for r in resp.data or []}


def filter_hidden_events(events, viewer_id: str | None):
    """Return events without those organized by a user the viewer blocked or who blocked the viewer.

    Events the viewer participates in are kept. Items that are not dicts (or are None) pass
    through untouched. Anonymous visitors (viewer_id None) see everything.
    """
    if not viewer_id or not events:
        return events
    hidden = get_hidden_user_ids(viewer_id)
    if not hidden:
        return events

    rows = [e for e in events if isinstance(e, dict)]
    backfill = _organizers(rows)

    def organizer(e):
        return _norm(e["created_by"] if "created_by" in e else backfill.get(str(e.get("id"))) or "")

    candidates = [str(e["id"]) for e in rows if e.get("id") and organizer(e) in hidden]
    joined = _joined_event_ids(viewer_id, candidates)
    return [
        e for e in events
        if not isinstance(e, dict) or organizer(e) not in hidden or str(e.get("id")) in joined
    ]


def is_event_hidden(event: dict, viewer_id: str | None) -> bool:
    """True when a single event row must be treated as not found for the viewer."""
    return bool(event) and bool(viewer_id) and not filter_hidden_events([event], viewer_id)


def hidden_events_filter(viewer_id: str | None) -> str | None:
    """A PostgREST `or` filter keeping only events the viewer may see, or None when nothing is hidden.

    Use as query.or_(filter) on the events table so pagination and counts stay correct.
    """
    if not viewer_id:
        return None
    hidden = sorted(get_hidden_user_ids(viewer_id))
    if not hidden:
        return None
    listed = ",".join(hidden)
    resp = (
        supabase.table("event_participants")
        .select("event_id, events!inner(created_by)")
        .eq("user_id", viewer_id)
        .in_("events.created_by", hidden)
        .execute()
    )
    joined = sorted({str(r["event_id"]) for r in resp.data or []})
    parts = ["created_by.is.null", f"created_by.not.in.({listed})"]
    if joined:
        parts.append(f"id.in.({','.join(joined)})")
    return ",".join(parts)
