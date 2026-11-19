"""Administrators remove events and chat messages (ticket #236).

Removing marks the row (removed_at, removed_by); nothing is deleted. Order of a removal:
  1. mark it removed (only if it is not removed yet, so two administrators cannot both do it);
  2. give the owner the warning (a failure undoes step 1, so the removal can be retried; the
     warning is marked with removal_key, so a retry after a lost response
     reuses this removal's own warning and never an earlier manual or unrelated warning about
     the same content, #236 and #255);
  3. notify the owner once ("Your content was removed");
  4. write the audit entry, with the report when the removal came from one;
  5. for an upcoming event, notify its participants (in the background: it can take long).
Every step is attempted. When step 3 or 4 fails, the removal and the warning stay, the participants are told
at once (a background task does not run when the answer is an error) and the answer is the coded 503
removal_followups_incomplete, listing what is missing. The same request again finds the content removed
with steps missing (pending_removal_steps) and creates only those steps: no new warning, no second
participant notification, the original removed_at / removed_by in the answer, and the recovered audit entry
names the original remover with retried:True (completed_by:<admin> when another administrator finished it).
A removal with nothing missing is still refused with 409 already_removed.
A removal that stayed without its warning (removal_incomplete: the warning and the undo both failed, so
nothing was written for it) is finished by the same request again: the retry gives the warning first (idempotent
by removal_key; when that fails again the answer is removal_incomplete again and nothing else is written), then
the notification and the audit entry. A removal from before #255 (warning without removal_key, notification with
or without the warning suffix) is recognised as finished and never gets a second warning.
Known edges:
  * a notification the owner deleted counts as missing, so a repeated request, also a second report about the
    same content, recreates it (and only it) instead of answering 409;
  * the identical messages of an administrator owner (no warning) are matched by their text;
  * participants are not notified again;
  * no lock: a retry that arrives while the first request is still between the mark and its steps can write the
    records twice, and when that first request's warning then fails and it undoes the mark, records can exist for
    content that is not removed. The retry re-reads removed_at just before writing and answers 409
    already_removed when the mark is gone, which narrows but does not close the window; two retries at the
    same moment are not locked against each other either;
  * the recovered audit entry carries the retry's report_id (or none), which can differ from the original
    removal's report;
  * a legacy removal (before #255) whose notification AND audit entry are both lost, and whose owner is no
    administrator, looks like a removal_incomplete one and gets a (keyed) warning on the retry.
"""
import logging
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.db.supabase_client import supabase
from app.services.audit_service import _people, record_audit
from app.services.warning_service import find_removal_warning, give_removal_warning

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
    return _incomplete_error(what)


def _incomplete_error(what: str) -> HTTPException:
    return removal_error(
        500, "removal_incomplete",
        f"The {what} was removed, but its owner could not be warned and the removal could not be undone. "
        "Tell a developer.",
    )


def _owner_message(what: str, has_warning: bool, quoted: str | None = None) -> str:
    message = f"Your content was removed. {what} was removed by an administrator"
    message += f': "{quoted}".' if quoted else "."
    if has_warning:
        message += " This counts as a warning."
    return message


def _warning_reason(what: str, quoted: str | None = None) -> str:
    return f"{what} was removed by an administrator" + (f': "{quoted}"' if quoted else ".")


def _about(kind: str, content_id) -> tuple:
    """(about_type, about_id) of the warning of a removal; the removal_key is 'about_type:about_id'."""
    return ("event" if kind == "event" else "chat_message"), str(content_id)


def _owner_notice_parts(kind: str, row: dict, title) -> tuple:
    """(owner id, event id, what, quoted): the ONE source of the owner notification text, used to create it
    and to look it up again, so the two cannot drift."""
    if kind == "event":
        return row.get("created_by"), row["id"], f'Your event "{title}"', None
    return row["sender_id"], row["event_id"], f'Your message in "{title}"', _snippet(row.get("content"))


def _notify_owner(owner_id: str, event_id: str, what: str, warning_id, quoted: str | None = None) -> bool:
    """The one notification the owner gets for a removal. It replaces the usual warning notification.
    Never raises; False when it could not be stored."""
    try:
        supabase.table("notifications").insert({
            "user_id": owner_id,
            "event_id": event_id,
            "type": CONTENT_REMOVED_NOTIFICATION_TYPE,
            "message": _owner_message(what, warning_id is not None, quoted),
            "is_read": False,
            "warning_id": warning_id,
            "created_at": _now(),
        }).execute()
        return True
    except Exception:
        # Not swallowed by the caller: the administrator is told (503 removal_followups_incomplete).
        logger.error("Could not notify the owner of removed content: owner=%s event=%s",
                     owner_id, event_id, exc_info=True)
        return False


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


def _result(removed_at: str, admin_id: str, report_id, warning, tolerate_read_failure=False, **ids) -> dict:
    """The answer body. In a recovery it runs after the writes and a retry would then be a 409, so there a
    failed profile read (tolerate_read_failure) gives removed_by null instead of a 500 that reopens the report."""
    try:
        remover = _people([admin_id]).get(admin_id)
    except Exception:
        if not tolerate_read_failure:
            raise
        logger.error("Could not load the remover of a removal for the answer: %s", ids, exc_info=True)
        remover = None
    return {
        **ids,
        "is_removed": True,
        "removed_at": removed_at,
        "removed_by": remover,
        "report_id": report_id,
        "warning_id": warning["id"] if warning else None,
    }


def _followups_error(failed: list, event_id, message_id=None) -> HTTPException:
    detail = {
        "code": "removal_followups_incomplete",
        "message": "The content is removed, and any warning is kept, but not everything was recorded. "
                   "Repeat the same request to finish.",
        "missing": failed,
        "event_id": str(event_id),
    }
    if message_id is not None:
        detail["message_id"] = message_id
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)


def _attempt(steps: list, notify, audit) -> list:
    """Run the wanted follow-up steps (all of them, whatever fails); returns the ones that failed."""
    failed = []
    if "owner_notification" in steps and not notify():
        failed.append("owner_notification")
    if "audit_entry" in steps and not audit():
        failed.append("audit_entry")
    return failed


def _audit_removal(kind: str, row: dict, title, admin_id, report_id, warning, retried_by=None) -> bool:
    """The audit entry of a removal. On a retry admin_id is the original remover and retried_by the
    administrator finishing it."""
    details = {"event_id": row["event_id"]} if kind == "message" else {}
    details.update({
        "report_id": report_id if report_id else "none",
        "owner_id": row["sender_id"] if kind == "message" else row.get("created_by"),
        "warning_id": warning["id"] if warning else "none",
    })
    if retried_by:
        details["retried"] = True
        if str(retried_by).lower() != str(admin_id).lower():
            details["completed_by"] = retried_by
    if kind == "event":
        action, entity_type, description = "event_removed", "event", f'Removed event "{title}"'
    else:
        action, entity_type, description = "message_removed", "chat_message", f'Removed a chat message in "{title}"'
    return record_audit(
        action=action,
        admin_id=admin_id,
        entity_type=entity_type,
        entity_id=row["id"],
        description=description + (f" from report {report_id}" if report_id else ""),
        details=details,
    )


def _removal_row(kind: str, content_id):
    """(row, title) of the content, or None when it does not exist."""
    if kind == "event":
        if not _is_uuid(content_id):
            return None
        row = _first(
            supabase.table("events").select("id, title, created_by, removed_at, removed_by")
            .eq("id", str(content_id)).limit(1).execute()
        )
        return (row, row.get("title")) if row else None
    row = _first(
        supabase.table("event_chats").select("id, event_id, sender_id, content, removed_at, removed_by")
        .eq("id", content_id).limit(1).execute()
    )
    if not row:
        return None
    event = _first(supabase.table("events").select("id, title").eq("id", row["event_id"]).limit(1).execute()) or {}
    return row, event.get("title") or "an event"


def _warning_of(kind: str, owner_id, content_id) -> dict | None:
    if not owner_id:
        return None
    about_type, about_id = _about(kind, content_id)
    return find_removal_warning(owner_id, f"{about_type}:{about_id}")


def _notify_owner_of(kind: str, row: dict, title, warning) -> bool:
    owner_id, event_id, what, quoted = _owner_notice_parts(kind, row, title)
    return _notify_owner(owner_id, event_id, what, warning["id"] if warning else None, quoted)


def _give_warning(kind: str, row: dict, title, admin_id):
    """The removal warning (idempotent by removal_key); None for an administrator owner. Raises on failure."""
    owner_id, _event_id, what, quoted = _owner_notice_parts(kind, row, title)
    about_type, about_id = _about(kind, row["id"])
    return give_removal_warning(owner_id, admin_id, _warning_reason(what, quoted), about_type, about_id)


def pending_removal_steps(kind: str, content_id) -> list:
    """The follow-up steps still missing for removed content, in the order owner_notification, audit_entry.

    [] when the content is not removed, does not exist (also hard-deleted) or is finished. Writes nothing."""
    found = _removal_row(kind, content_id)
    if not found or not found[0].get("removed_at"):
        return []
    row, title = found
    pending = []
    owner_id, event_id, what, quoted = _owner_notice_parts(kind, row, title)
    if owner_id:
        warning = _warning_of(kind, owner_id, row["id"])
        query = (
            supabase.table("notifications").select("id")
            .eq("user_id", owner_id).eq("type", CONTENT_REMOVED_NOTIFICATION_TYPE)
        )
        if warning:
            query = query.eq("warning_id", warning["id"])
        else:
            # No keyed warning: an administrator owner (plain text) or a removal from before #255, whose
            # warning has no removal_key but whose notification has the warning suffix.
            query = query.eq("event_id", event_id).in_(
                "message", [_owner_message(what, False, quoted), _owner_message(what, True, quoted)])
        if not query.limit(1).execute().data:
            pending.append("owner_notification")
    audit = (
        supabase.table("logs").select("id")
        .eq("type", "event_removed" if kind == "event" else "message_removed")
        .eq("entity_type", "event" if kind == "event" else "chat_message")
        .eq("entity_id", str(row["id"])).limit(1).execute()
    )
    if not audit.data:
        pending.append("audit_entry")
    return pending


def _recover_removal(kind: str, row: dict, title, missing: list, admin_id, report_id) -> dict:
    """Create only the missing steps of an earlier removal; the warning is the existing one.

    Exception: when nothing at all was written for the removal (removal_incomplete: no warning, no notification,
    no audit entry) the warning is given first."""
    owner_id, event_id, what, _quoted = _owner_notice_parts(kind, row, title)
    still = _removal_row(kind, row["id"])
    if not still or not still[0].get("removed_at"):  # the first request undid its mark meanwhile (no lock)
        raise removal_error(409, "already_removed",
                            f"This {'event' if kind == 'event' else 'message'} is already removed.")
    original = row.get("removed_by") or admin_id
    warning = _warning_of(kind, owner_id, row["id"])
    if warning is None and owner_id and missing == ["owner_notification", "audit_entry"]:
        try:
            warning = _give_warning(kind, row, title, original)
        except Exception:
            logger.error("Could not give the removal warning on a retry: %s %s", kind, row["id"], exc_info=True)
            raise _incomplete_error("event" if kind == "event" else "message")
    failed = _attempt(
        missing,
        lambda: _notify_owner_of(kind, row, title, warning),
        lambda: _audit_removal(kind, row, title, original, report_id, warning, retried_by=admin_id),
    )
    if failed:
        raise _followups_error(failed, event_id, row["id"] if kind == "message" else None)
    if kind == "event":
        return _result(row["removed_at"], original, report_id, warning, True, event_id=str(row["id"]))
    return _result(row["removed_at"], original, report_id, warning, True, event_id=str(event_id),
                   message_id=row["id"])


def remove_event(event_id: str, admin_id: str, report_id: int | None = None, background_tasks=None) -> dict:
    if not _is_uuid(event_id):
        raise removal_error(404, "event_not_found", "Event not found.")
    event = _first(
        supabase.table("events")
        .select("id, title, created_by, status, start_datetime, removed_at, removed_by")
        .eq("id", event_id)
        .limit(1)
        .execute()
    )
    if not event:
        raise removal_error(404, "event_not_found", "Event not found.")
    missing = []
    if event.get("removed_at"):
        missing = pending_removal_steps("event", event["id"])
        if not missing:
            raise removal_error(409, "already_removed", "This event is already removed.")
    _check_report(report_id, "event", event_id=event["id"])
    if missing:
        return _recover_removal("event", event, event.get("title"), missing, admin_id, report_id)

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
            warning = _give_warning("event", event, title, admin_id)
        except Exception:
            logger.error("Could not give the removal warning: event=%s owner=%s", event["id"], owner_id,
                         exc_info=True)
            raise _undo_removal("events", event["id"], admin_id, "event")

    failed = _attempt(
        (["owner_notification"] if owner_id else []) + ["audit_entry"],
        lambda: _notify_owner_of("event", event, title, warning),
        lambda: _audit_removal("event", event, title, admin_id, report_id, warning),
    )

    if _is_upcoming(event):
        if background_tasks is not None and not failed:
            background_tasks.add_task(_notify_participants, event)
        else:
            _notify_participants(event)
    if failed:
        raise _followups_error(failed, event["id"])
    return _result(removed_at, admin_id, report_id, warning, event_id=str(event["id"]))


def remove_message(event_id: str, message_id: int, admin_id: str, report_id: int | None = None) -> dict:
    if not _is_uuid(event_id):
        raise removal_error(404, "message_not_found", "Message not found.")
    message = _first(
        supabase.table("event_chats")
        .select("id, event_id, sender_id, type, content, removed_at, removed_by")
        .eq("id", message_id)
        .eq("event_id", event_id)
        .limit(1)
        .execute()
    )
    if not message:
        raise removal_error(404, "message_not_found", "Message not found.")
    if message.get("type") == "notification" or not message.get("sender_id"):
        raise removal_error(400, "cannot_remove_system_message", "System messages cannot be removed.")
    missing = []
    if message.get("removed_at"):
        missing = pending_removal_steps("message", message["id"])
        if not missing:
            raise removal_error(409, "already_removed", "This message is already removed.")
    _check_report(report_id, "message", message_id=message["id"])

    if missing:
        event = _first(supabase.table("events").select("id, title").eq("id", event_id).limit(1).execute()) or {}
        return _recover_removal("message", message, event.get("title") or "an event", missing, admin_id, report_id)

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
    try:
        warning = _give_warning("message", message, title, admin_id)
    except Exception:
        logger.error("Could not give the removal warning: message=%s owner=%s", message["id"], owner_id,
                     exc_info=True)
        raise _undo_removal("event_chats", message["id"], admin_id, "message")

    failed = _attempt(
        ["owner_notification", "audit_entry"],
        lambda: _notify_owner_of("message", message, title, warning),
        lambda: _audit_removal("message", message, title, admin_id, report_id, warning),
    )
    if failed:
        raise _followups_error(failed, event_id, message["id"])
    return _result(removed_at, admin_id, report_id, warning, event_id=str(event_id), message_id=message["id"])
