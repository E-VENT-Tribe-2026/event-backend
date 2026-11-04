import math
import logging
from fastapi import HTTPException, status
from app.db.supabase_client import supabase
from app.core.dependencies import is_admin_role
from app.services.audit_service import _people
from app.services.removed_content import LOOKUP_CHUNK
from app.services.report_service import report_error

logger = logging.getLogger(__name__)

_LIST_COLUMNS = "id, status, reason, created_at, target_type, origin, reporter_id, event_id, reported_user_id, message_id"
_EVENT_COLUMNS = "id, title, banner_url, created_by, removed_at"


def _newest_first(query):
    return query.order("created_at", desc=True).order("id", desc=True)


def _events_by_id(ids) -> dict:
    ids = list(dict.fromkeys(i for i in ids if i))
    if not ids:
        return {}
    found = {}
    # In chunks: a long id list would make the request address too long for PostgREST.
    for start in range(0, len(ids), LOOKUP_CHUNK):
        res = supabase.table("events").select(_EVENT_COLUMNS).in_("id", ids[start:start + LOOKUP_CHUNK]).execute()
        found.update({row["id"]: row for row in (res.data or [])})
    return found


def _people_by_id(ids) -> dict:
    """audit_service._people, one query per LOOKUP_CHUNK ids, results merged."""
    ids = list(dict.fromkeys(i for i in ids if i))
    found = {}
    for start in range(0, len(ids), LOOKUP_CHUNK):
        found.update(_people(ids[start:start + LOOKUP_CHUNK]))
    return found


def _report_event_card(event: dict | None) -> dict | None:
    if not event:
        return None
    return {
        "id": str(event["id"]),
        "title": event.get("title"),
        "banner": event.get("banner_url"),
        "banner_url": event.get("banner_url"),
    }


def _reported(row: dict, people: dict, events: dict) -> dict:
    target = row["target_type"]
    message = None
    if target == "message":
        message = {"id": row["message_id"], "event_id": row.get("event_id")}
    return {
        "type": target,
        "event": _report_event_card(events.get(row.get("event_id"))) if target == "event" else None,
        "user": people.get(row.get("reported_user_id")) if target != "event" else None,
        "message": message,
    }


def _item(row: dict, people: dict, events: dict) -> dict:
    return {
        "id": row["id"],
        "status": row["status"],
        "reason": row["reason"],
        "created_at": str(row["created_at"]),
        "target_type": row["target_type"],
        "origin": row["origin"],
        "reporter": people.get(row.get("reporter_id")),
        "reported": _reported(row, people, events),
    }


def _items(rows: list[dict]) -> list[dict]:
    """Report entries with their people and events loaded in two batched queries."""
    people = _people_by_id([i for r in rows for i in (r.get("reporter_id"), r.get("reported_user_id"))])
    events = _events_by_id([r.get("event_id") for r in rows])
    return [_item(r, people, events) for r in rows]


def _load_failed(what: str, error: Exception) -> HTTPException:
    logger.error(f"{what} failed: {error}", exc_info=True)
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not load reports.")


def list_open_reports() -> dict:
    """Every open report, newest first."""
    try:
        res = _newest_first(
            supabase.table("reports").select(_LIST_COLUMNS, count="exact").eq("status", "open")
        ).execute()
        items = _items(res.data or [])
    except Exception as e:
        raise _load_failed("list_open_reports", e)
    total = res.count if res.count is not None else len(items)
    if len(items) < total:
        logger.warning(f"list_open_reports truncated: returned {len(items)} of {total} open reports")
    return {"total": total, "items": items}


def list_reports(page: int = 1, limit: int = 20) -> dict:
    """Every report in pages, newest first."""
    offset = (page - 1) * limit
    try:
        res = _newest_first(
            supabase.table("reports").select(_LIST_COLUMNS, count="exact")
        ).range(offset, offset + limit - 1).execute()
        items = _items(res.data or [])
    except Exception as e:
        raise _load_failed("list_reports", e)
    total = res.count if res.count is not None else len(items)
    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": max(1, math.ceil(total / limit)),
    }


def _role_of(user_id) -> str | None:
    if not user_id:
        return None
    res = supabase.table("profiles").select("role").eq("id", user_id).limit(1).execute()
    return res.data[0].get("role") if res.data else None


def _message_removed(message_id) -> bool:
    """True when the message is marked removed or no longer exists (hard-deleted, e.g. by cascade)."""
    res = supabase.table("event_chats").select("removed_at").eq("id", message_id).limit(1).execute()
    if not res.data:
        return True
    return bool(res.data[0].get("removed_at"))


def get_report_details(report_id: int) -> dict:
    """One report with its description, chat context, outcome and the live state of what was reported.

    content_removed is true when the reported event/message is marked removed or no longer exists;
    it is always false for a user report.
    """
    try:
        res = supabase.table("reports").select("*").eq("id", report_id).limit(1).execute()
        row = res.data[0] if res.data else None
        if row is None:
            raise report_error(404, "report_not_found", "This report does not exist.")

        target = row["target_type"]
        event = _events_by_id([row.get("event_id")]).get(row.get("event_id"))
        people = _people_by_id([row.get("reporter_id"), row.get("reported_user_id"), row.get("closed_by")])
        detail = _item(row, people, {row.get("event_id"): event} if event else {})

        if target == "event":
            # Deleted content counts as removed: the event is marked removed or is gone altogether.
            content_removed = event is None or bool(event.get("removed_at"))
            reported_user_id = event.get("created_by") if event else None
        else:
            # A message counts as removed when marked removed or deleted; a user report has no removable content.
            content_removed = target == "message" and _message_removed(row["message_id"])
            reported_user_id = row.get("reported_user_id")

        from_chat = row["origin"] == "event_chat"
        detail.update({
            "description": row.get("description"),
            "event": _report_event_card(event) if from_chat else None,
            "chat_context": row.get("chat_context") if from_chat else None,
            "outcome": row.get("outcome"),
            "closed_by": people.get(row.get("closed_by")),
            "closed_at": str(row["closed_at"]) if row.get("closed_at") else None,
            "content_removed": content_removed,
            "reported_user_is_administrator": is_admin_role(_role_of(reported_user_id)),
        })
        return detail
    except HTTPException:
        raise
    except Exception as e:
        raise _load_failed("get_report_details", e)
