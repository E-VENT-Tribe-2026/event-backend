"""Administrators remove events and chat messages (ticket #236).

Removing marks the row (removed_at, removed_by); nothing is deleted. Order of a removal:
  1. mark it removed (only if it is not removed yet, so two administrators cannot both do it);
  2. give the owner the warning (a failure undoes step 1, so the removal can be retried; the
     warning is idempotent, so a retry never warns twice);
  3. notify the owner once ("Your content was removed");
  4. write the audit entry, with the report when the removal came from one;
  5. for an upcoming event, notify its participants (in the background: it can take long).
Steps 3 to 5 never fail the removal: it already happened.
"""
import logging
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException

from app.db.supabase_client import supabase
from app.services.audit_service import _people, record_audit
from app.services.warning_service import give_removal_warning

logger = logging.getLogger(__name__)

CONTENT_REMOVED_NOTIFICATION_TYPE = "content_removed"
EVENT_REMOVED_NOTIFICATION_TYPE = "event_removed"
MESSAGE_SNIPPET_LENGTH = 100


def removal_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _first(resp):
    data = resp.data
    if isinstance(data, list):
        return data[0] if data else None
    return data or None


def _is_uuid(value) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


def _snippet(text) -> str:
    one_line = " ".join(str(text or "").split())
    if len(one_line) > MESSAGE_SNIPPET_LENGTH:
        return one_line[:MESSAGE_SNIPPET_LENGTH].rstrip() + "..."
    return one_line


def _check_report(report_id, target_type: str, **must_match) -> None:
    """A removal from a report must name a report about exactly this event or message."""
    if report_id is None:
        return
    report = _first(
        supabase.table("reports")
        .select("id, target_type, event_id, message_id")
        .eq("id", report_id)
        .limit(1)
        .execute()
    )
    if not report:
        raise removal_error(404, "report_not_found", "Report not found.")
    if report.get("target_type") != target_type or any(
        str(report.get(column)) != str(value) for column, value in must_match.items()
    ):
        raise removal_error(400, "report_mismatch", "This report is not about this content.")


def _undo_removal(table: str, row_id, admin_id: str, what: str) -> HTTPException:
    """Undo the removal mark after the warning could not be stored; returns the error to raise.

    Only this administrator's own mark is undone. If the undo fails too, the content stays removed
    without a warning, so the error says so instead of asking for a retry that would get a 409.
    """
    try:
        undone = (
            supabase.table(table)
            .update({"removed_at": None, "removed_by": None})
            .eq("id", row_id)
            .eq("removed_by", admin_id)
            .execute()
        )
        if undone.data:
            return removal_error(500, "removal_failed", f"The {what} could not be removed. Please try again.")
    except Exception:
        pass
    logger.error("Could not undo the removal mark: %s %s", table, row_id, exc_info=True)
    return removal_error(
        500, "removal_incomplete",
        f"The {what} was removed, but its owner could not be warned and the removal could not be undone. "
        "Tell a developer.",
    )


def _notify_owner(owner_id: str, event_id: str, what: str, warning_id, quoted: str | None = None) -> None:
    """The one notification the owner gets for a removal. It replaces the usual warning notification."""
    message = f"Your content was removed. {what} was removed by an administrator"
    message += f': "{quoted}".' if quoted else "."
    if warning_id is not None:
        message += " This counts as a warning."
    try:
        supabase.table("notifications").insert({
            "user_id": owner_id,
            "event_id": event_id,
            "type": CONTENT_REMOVED_NOTIFICATION_TYPE,
            "message": message,
            "is_read": False,
            "warning_id": warning_id,
            "created_at": _now(),
        }).execute()
    except Exception:
        # With a warning, it still reaches the owner through /warnings/pending.
        logger.error("Could not notify the owner of removed content: owner=%s event=%s",
                     owner_id, event_id, exc_info=True)


def _notify_participants(event: dict) -> int:
    """Tell the participants of a removed upcoming event, without the reason. Returns how many."""
    from app.services.notification_service import create_notification

    try:
        rows = (
            supabase.table("event_participants").select("user_id").eq("event_id", event["id"]).execute()
        ).data or []
    except Exception:
        logger.error("Could not load the participants of removed event %s", event["id"], exc_info=True)
        return 0

    owner = str(event.get("created_by") or "").lower()
    notified = 0
    for user_id in dict.fromkeys(r["user_id"] for r in rows if r.get("user_id")):
        if str(user_id).lower() == owner:
            continue  # the organizer gets "Your content was removed" instead
        try:
            create_notification(
                user_id, event["id"], EVENT_REMOVED_NOTIFICATION_TYPE,
                f'Event "{event.get("title")}" was removed by an administrator.',
            )
            notified += 1
        except Exception:
            logger.error("Could not notify participant %s of removed event %s", user_id, event["id"],
                         exc_info=True)
    return notified


def _is_upcoming(event: dict) -> bool:
    if str(event.get("status") or "").lower() == "cancelled":
        return False
    raw = event.get("start_datetime")
    if isinstance(raw, datetime):
        start = raw
    else:
        try:
            start = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return False
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    return start > datetime.now(timezone.utc)


def _result(removed_at: str, admin_id: str, report_id, warning, **ids) -> dict:
    return {
        **ids,
        "is_removed": True,
        "removed_at": removed_at,
        "removed_by": _people([admin_id]).get(admin_id),
        "report_id": report_id,
        "warning_id": warning["id"] if warning else None,
    }


def remove_event(event_id: str, admin_id: str, report_id: int | None = None, background_tasks=None) -> dict:
    if not _is_uuid(event_id):
        raise removal_error(404, "event_not_found", "Event not found.")
    event = _first(
        supabase.table("events")
        .select("id, title, created_by, status, start_datetime, removed_at")
        .eq("id", event_id)
        .limit(1)
        .execute()
    )
    if not event:
        raise removal_error(404, "event_not_found", "Event not found.")
    if event.get("removed_at"):
        raise removal_error(409, "already_removed", "This event is already removed.")
    _check_report(report_id, "event", event_id=event["id"])

    removed_at = _now()
    marked = (
        supabase.table("events")
        .update({"removed_at": removed_at, "removed_by": admin_id})
        .eq("id", event["id"])
        .is_("removed_at", "null")  # two administrators at once: only the first one wins
        .execute()
    )
    if not marked.data:
        raise removal_error(409, "already_removed", "This event is already removed.")

    owner_id = event.get("created_by")
    title = event.get("title")
    warning = None
    if owner_id:
        try:
            warning = give_removal_warning(
                owner_id, admin_id, f'Your event "{title}" was removed by an administrator.',
                "event", str(event["id"]),
            )
        except Exception:
            logger.error("Could not give the removal warning: event=%s owner=%s", event["id"], owner_id,
                         exc_info=True)
            raise _undo_removal("events", event["id"], admin_id, "event")
        _notify_owner(owner_id, event["id"], f'Your event "{title}"', warning["id"] if warning else None)

    record_audit(
        action="event_removed",
        admin_id=admin_id,
        entity_type="event",
        entity_id=event["id"],
        description=f'Removed event "{title}"' + (f" from report {report_id}" if report_id else ""),
        details={
            "report_id": report_id if report_id else "none",
            "owner_id": owner_id,
            "warning_id": warning["id"] if warning else "none",
        },
    )

    if _is_upcoming(event):
        if background_tasks is not None:
            background_tasks.add_task(_notify_participants, event)
        else:
            _notify_participants(event)
    return _result(removed_at, admin_id, report_id, warning, event_id=str(event["id"]))


def remove_message(event_id: str, message_id: int, admin_id: str, report_id: int | None = None) -> dict:
    if not _is_uuid(event_id):
        raise removal_error(404, "message_not_found", "Message not found.")
    message = _first(
        supabase.table("event_chats")
        .select("id, event_id, sender_id, type, content, removed_at")
        .eq("id", message_id)
        .eq("event_id", event_id)
        .limit(1)
        .execute()
    )
    if not message:
        raise removal_error(404, "message_not_found", "Message not found.")
    if message.get("type") == "notification" or not message.get("sender_id"):
        raise removal_error(400, "cannot_remove_system_message", "System messages cannot be removed.")
    if message.get("removed_at"):
        raise removal_error(409, "already_removed", "This message is already removed.")
    _check_report(report_id, "message", message_id=message["id"])

    removed_at = _now()
    marked = (
        supabase.table("event_chats")
        .update({"removed_at": removed_at, "removed_by": admin_id})
        .eq("id", message["id"])
        .is_("removed_at", "null")
        .execute()
    )
    if not marked.data:
        raise removal_error(409, "already_removed", "This message is already removed.")

    event = _first(supabase.table("events").select("id, title").eq("id", event_id).limit(1).execute()) or {}
    title = event.get("title") or "an event"
    owner_id = message["sender_id"]
    snippet = _snippet(message.get("content"))
    try:
        warning = give_removal_warning(
            owner_id, admin_id, f'Your message in "{title}" was removed by an administrator: "{snippet}"',
            "chat_message", str(message["id"]),
        )
    except Exception:
        logger.error("Could not give the removal warning: message=%s owner=%s", message["id"], owner_id,
                     exc_info=True)
        raise _undo_removal("event_chats", message["id"], admin_id, "message")
    _notify_owner(owner_id, event_id, f'Your message in "{title}"',
                  warning["id"] if warning else None, quoted=snippet)

    record_audit(
        action="message_removed",
        admin_id=admin_id,
        entity_type="chat_message",
        entity_id=message["id"],
        description=f'Removed a chat message in "{title}"' + (f" from report {report_id}" if report_id else ""),
        details={
            "event_id": event_id,
            "report_id": report_id if report_id else "none",
            "owner_id": owner_id,
            "warning_id": warning["id"] if warning else "none",
        },
    )
    return _result(removed_at, admin_id, report_id, warning, event_id=str(event_id), message_id=message["id"])
