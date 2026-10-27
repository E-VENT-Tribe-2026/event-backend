"""Removed events and chat messages (ticket #236).

An administrator removes an event or a chat message by marking it (removed_at, removed_by);
nothing is deleted. Users never see removed events, and removed messages come back without
their text. Kept free of other service imports so any service can use it.
"""
import logging

from fastapi import HTTPException

from app.db.supabase_client import supabase

logger = logging.getLogger(__name__)

EVENT_REMOVED_CODE = "event_removed"
EVENT_REMOVED_MESSAGE = "This event was removed by an administrator."
MESSAGE_REMOVED_CODE = "message_removed"
LOOKUP_CHUNK = 100


def event_removed_error() -> HTTPException:
    """410 for anything a user does with a removed event (opening it, joining it, its chat...)."""
    return HTTPException(
        status_code=410,
        detail={"code": EVENT_REMOVED_CODE, "message": EVENT_REMOVED_MESSAGE},
    )


def message_removed_error() -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"code": MESSAGE_REMOVED_CODE, "message": "This message was removed by an administrator."},
    )


def removed_event_ids(event_ids) -> set:
    """The subset of event_ids that are removed, in one query."""
    ids = list(dict.fromkeys(str(i) for i in event_ids if i))
    removed = set()
    # In chunks: a long id list would make the request address too long for PostgREST.
    for start in range(0, len(ids), LOOKUP_CHUNK):
        resp = (
            supabase.table("events")
            .select("id, removed_at")
            .in_("id", ids[start:start + LOOKUP_CHUNK])
            .execute()
        )
        removed |= {str(r["id"]) for r in (resp.data or []) if r.get("removed_at")}
    return removed


def filter_removed_events(events):
    """Return events without the removed ones.

    Rows that carry removed_at (select *) are judged by it; rows that do not (RPC results,
    explicit column lists) are looked up by id in one query. Items that are not dicts pass through.
    """
    if not events:
        return events
    rows = [e for e in events if isinstance(e, dict)]
    unknown = [e["id"] for e in rows if "removed_at" not in e and e.get("id")]
    removed = removed_event_ids(unknown)

    def is_removed(e):
        if "removed_at" in e:
            return bool(e["removed_at"])
        return str(e.get("id")) in removed

    return [e for e in events if not isinstance(e, dict) or not is_removed(e)]


def assert_event_not_removed(event_id: str) -> None:
    """Raise 410 when the event is removed. Used before anything is shown from or added to its chat."""
    resp = (
        supabase.table("events")
        .select("removed_at")
        .eq("id", event_id)
        .limit(1)
        .execute()
    )
    row = resp.data[0] if isinstance(resp.data, list) and resp.data else resp.data
    if isinstance(row, dict) and row.get("removed_at"):
        raise event_removed_error()
