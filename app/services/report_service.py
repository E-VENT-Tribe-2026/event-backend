"""Reporting events, users and chat messages (ticket #234).

Reports are stored in `reports` (supabase/migrations/20261025120000_reports.sql), which only
the backend can read or change. A report opened from an event chat carries a copy of part of
the chat, so the administrator sees what was said even if the messages are later edited or removed.
"""
import logging

from fastapi import HTTPException

from app.db.supabase_client import supabase
from app.schemas.report_schema import (
    ORIGIN_EVENT_CHAT,
    TARGET_EVENT,
    TARGET_MESSAGE,
    TARGET_USER,
    ReportCreate,
)

logger = logging.getLogger(__name__)

REPORTS_TABLE = "reports"
STATUS_OPEN = "open"
CONTEXT_MESSAGES_AROUND = 5
CONTEXT_LAST_MESSAGES = 10
UNIQUE_VIOLATION = "23505"
FOREIGN_KEY_VIOLATION = "23503"

CONFIRMATION_MESSAGE = "Report sent. Thank you, an administrator will review it."


def report_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _first(resp):
    data = resp.data
    if isinstance(data, list):
        return data[0] if data else None
    return data or None


def _same(a, b) -> bool:
    return a is not None and b is not None and str(a).lower() == str(b).lower()


def _organizer_id(event_id: str):
    """The event's organizer. Unlike chat_service._get_organizer_id, a failed lookup raises."""
    event = _first(supabase.table("events").select("created_by").eq("id", event_id).limit(1).execute())
    return (event or {}).get("created_by")


def _is_in_chat(user_id: str, event_id: str, organizer_id=None) -> bool:
    """The event's participants and its organizer are in its chat (same rule as chat_service)."""
    joined = (
        supabase.table("event_participants")
        .select("user_id")
        .eq("event_id", event_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if joined.data:
        return True
    return _same(organizer_id if organizer_id is not None else _organizer_id(event_id), user_id)


def _require_in_chat(user_id: str, event_id: str, organizer_id=None) -> None:
    if not _is_in_chat(user_id, event_id, organizer_id):
        raise report_error(403, "not_in_chat", "You can only report from an event chat you are in.")


def _sender_names(sender_ids: list) -> dict:
    """Display names for the stored chat copy. A failed lookup raises: no "Unknown" is saved by mistake."""
    ids = list(dict.fromkeys(sender_ids))
    if not ids:
        return {}
    rows = supabase.table("profiles").select("id, username, full_name").in_("id", ids).execute().data or []
    return {r["id"]: (r.get("full_name") or r.get("username") or "Unknown") for r in rows}


def _chat_context(rows: list, reported_id=None) -> list:
    """The stored copy of chat messages: enough to read the conversation without the chat."""
    names = _sender_names([r["sender_id"] for r in rows if r.get("sender_id")])
    context = []
    for r in rows:
        sender_id = r.get("sender_id")
        entry = {
            "id": r["id"],
            "type": r.get("type") or "chat",
            "sender_id": sender_id,
            "sender_name": names.get(sender_id, "Unknown") if sender_id else "System",
            "content": r.get("content"),
            "created_at": r.get("created_at"),
        }
        if reported_id is not None:
            entry["reported"] = r["id"] == reported_id
        context.append(entry)
    return context


def _message_context(event_id: str, message: dict) -> list:
    """The reported message, the five messages before it and the five after it."""
    before = (
        supabase.table("event_chats").select("*").eq("event_id", event_id)
        .lt("id", message["id"]).order("id", desc=True).limit(CONTEXT_MESSAGES_AROUND).execute()
    ).data or []
    after = (
        supabase.table("event_chats").select("*").eq("event_id", event_id)
        .gt("id", message["id"]).order("id", desc=False).limit(CONTEXT_MESSAGES_AROUND).execute()
    ).data or []
    return _chat_context(list(reversed(before)) + [message] + after, reported_id=message["id"])


def _event_context(event_id: str) -> list:
    """The last 10 messages of the chat right now."""
    last = (
        supabase.table("event_chats").select("*").eq("event_id", event_id)
        .order("id", desc=True).limit(CONTEXT_LAST_MESSAGES).execute()
    ).data or []
    return _chat_context(list(reversed(last)))


def _already_reported() -> HTTPException:
    return report_error(409, "already_reported", "You have already reported this. An administrator will review it.")


def _resolve_event(reporter_id: str, body: ReportCreate) -> dict:
    event = _first(
        supabase.table("events").select("id, created_by").eq("id", body.target_id).limit(1).execute()
    )
    if not event:
        raise report_error(404, "event_not_found", "Event not found.")
    if _same(event.get("created_by"), reporter_id):
        raise report_error(400, "cannot_report_own_event", "You cannot report your own event.")
    context = None
    if body.origin == ORIGIN_EVENT_CHAT:
        _require_in_chat(reporter_id, event["id"], organizer_id=event.get("created_by"))
        context = _event_context(event["id"])
    return {"event_id": event["id"], "chat_context": context}


def _resolve_user(reporter_id: str, body: ReportCreate) -> dict:
    if _same(body.target_id, reporter_id):
        raise report_error(400, "cannot_report_own_profile", "You cannot report your own profile.")
    profile = _first(
        supabase.table("profiles").select("id").eq("id", body.target_id).limit(1).execute()
    )
    if not profile:
        raise report_error(404, "user_not_found", "User not found.")
    return {"reported_user_id": profile["id"]}


def _resolve_message(reporter_id: str, body: ReportCreate) -> dict:
    message = _first(
        supabase.table("event_chats").select("*").eq("id", int(body.target_id)).limit(1).execute()
    )
    if not message:
        raise report_error(404, "message_not_found", "Message not found.")
    # The reporter must be in the chat before anything else about the message is revealed.
    _require_in_chat(reporter_id, message["event_id"])
    if message.get("type") == "notification" or not message.get("sender_id"):
        raise report_error(400, "cannot_report_system_message", "System messages cannot be reported.")
    if _same(message["sender_id"], reporter_id):
        raise report_error(400, "cannot_report_own_message", "You cannot report your own message.")
    if not _first(supabase.table("profiles").select("id").eq("id", message["sender_id"]).limit(1).execute()):
        raise report_error(404, "user_not_found", "The sender of this message no longer exists.")
    return {
        "event_id": message["event_id"],
        "message_id": message["id"],
        "reported_user_id": message["sender_id"],
        "chat_context": _message_context(message["event_id"], message),
    }


_RESOLVERS = {
    TARGET_EVENT: _resolve_event,
    TARGET_USER: _resolve_user,
    TARGET_MESSAGE: _resolve_message,
}

_ITEM_COLUMN = {TARGET_EVENT: "event_id", TARGET_USER: "reported_user_id", TARGET_MESSAGE: "message_id"}


def _has_open_report(reporter_id: str, body: ReportCreate, target: dict) -> bool:
    column = _ITEM_COLUMN[body.target_type]
    resp = (
        supabase.table(REPORTS_TABLE)
        .select("id")
        .eq("reporter_id", reporter_id)
        .eq("target_type", body.target_type)
        .eq(column, target[column])
        .eq("status", STATUS_OPEN)
        .limit(1)
        .execute()
    )
    return bool(resp.data)


def _save_failed() -> HTTPException:
    return report_error(500, "report_failed", "Your report could not be saved. Please try again.")


def create_report(reporter_id: str, body: ReportCreate) -> dict:
    """Check who and what is reported, then store an Open report and return its confirmation."""
    try:
        target = _RESOLVERS[body.target_type](reporter_id, body)
        duplicate = _has_open_report(reporter_id, body, target)
    except HTTPException:
        raise
    except Exception:
        # A failed lookup must not turn into a wrong answer (403, "Unknown" names) or a bare 500.
        logger.error("Report lookup failed: reporter=%s target=%s/%s", reporter_id,
                     body.target_type, body.target_id, exc_info=True)
        raise _save_failed()
    if duplicate:
        raise _already_reported()

    row = {
        "reporter_id": reporter_id,
        "target_type": body.target_type,
        "event_id": target.get("event_id"),
        "reported_user_id": target.get("reported_user_id"),
        "message_id": target.get("message_id"),
        "reason": body.reason,
        "description": body.description,
        "origin": body.origin,
        "status": STATUS_OPEN,
        "chat_context": target.get("chat_context"),
    }
    try:
        resp = supabase.table(REPORTS_TABLE).insert(row).execute()
    except Exception as exc:
        # Two simultaneous requests: the partial unique index lets only one open report through.
        code = getattr(exc, "code", None)
        if code == UNIQUE_VIOLATION:
            raise _already_reported()
        if code == FOREIGN_KEY_VIOLATION:
            # The event or user was deleted between the check and the insert.
            raise report_error(404, "item_not_found", "What you are reporting no longer exists.")
        logger.error("Failed to store report: reporter=%s target=%s/%s", reporter_id,
                     body.target_type, body.target_id, exc_info=True)
        raise _save_failed()

    saved = _first(resp)
    if not saved:
        raise _save_failed()

    return {
        "id": saved["id"],
        "status": saved.get("status", STATUS_OPEN),
        "target_type": body.target_type,
        "target_id": body.target_id,
        "reason": body.reason,
        "origin": body.origin,
        "created_at": saved.get("created_at"),
        "message": CONFIRMATION_MESSAGE,
    }
