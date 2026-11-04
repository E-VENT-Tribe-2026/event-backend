"""Administrators dismiss a report or act on it (ticket #235).

Order of every request:
  1. load the report (404) and refuse one that is not open (409), before any other check;
  2. validate the action with reads only, so a refusal changes nothing;
  3. claim the report: one conditional update open -> closed, so two administrators cannot both close it;
  4. run the existing service (warning, suspension or removal);
  5. a failure after the claim reopens the report (only this administrator's own closure) and the
     original error is raised unchanged, UNLESS the service had already done its work when it raised
     (the reused services are not atomic): then the report stays closed, the error is logged and the
     request goes on as a success, so a retry cannot warn or remove twice. When that cannot be told,
     the report stays closed and the original error is raised (CRITICAL log + audit entry for a human);
  6. write the report-level audit entry and return the report details (a body built from what is known
     when loading them fails twice, so a success is never turned into a 500).
"""
import logging
from datetime import datetime, timezone

from fastapi import HTTPException

from app.core.dependencies import is_admin_role
from app.db.supabase_client import supabase
from app.services.admin_report_service import get_report_details
from app.services.audit_service import record_audit
from app.services.content_removal_service import remove_event, remove_message
from app.services.report_service import report_error
from app.services.suspension_service import suspend_user
from app.services.warning_service import give_warning

logger = logging.getLogger(__name__)

REOPEN_ATTEMPTS = 3

_OUTCOMES = {"warn": "warned", "suspend": "suspended", "remove_content": "content_removed"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _first(resp):
    return resp.data[0] if resp.data else None


def load_report(report_id: int) -> dict:
    report = _first(supabase.table("reports").select("*").eq("id", report_id).limit(1).execute())
    if report is None:
        raise report_error(404, "report_not_found", "This report does not exist.")
    if report.get("status") != "open":
        raise report_error(409, "report_closed", "This report is already closed.")
    return report


def _event_of(report: dict) -> dict | None:
    if not report.get("event_id"):
        return None
    return _first(
        supabase.table("events").select("id, created_by, removed_at").eq("id", report["event_id"]).limit(1).execute()
    )


def resolve_target(report: dict) -> dict:
    """The profile that a warning or suspension goes to: the reported user, or the organizer of the event."""
    if report["target_type"] == "event":
        event = _event_of(report)
        target_id = event.get("created_by") if event else None
    else:
        target_id = report.get("reported_user_id")
    profile = None
    if target_id:
        profile = _first(
            supabase.table("profiles").select("id, role, suspended_at").eq("id", target_id).limit(1).execute()
        )
    if profile is None:
        raise report_error(404, "reported_user_not_found", "The reported user no longer exists.")
    return profile


def _about(report: dict) -> tuple[str, str]:
    """What a warning from this report is about."""
    if report["target_type"] == "event":
        return "event", str(report["event_id"])
    if report["target_type"] == "message":
        return "chat_message", str(report["message_id"])
    return "profile", str(report["reported_user_id"])


def validate_warn(report: dict) -> dict:
    target = resolve_target(report)
    if is_admin_role(target.get("role")):
        raise report_error(400, "reported_user_is_administrator", "Administrator accounts cannot be warned.")
    return target


def validate_suspend(report: dict) -> dict:
    target = resolve_target(report)
    if is_admin_role(target.get("role")):
        raise report_error(400, "reported_user_is_administrator", "Administrator accounts cannot be suspended.")
    if target.get("suspended_at"):
        raise report_error(409, "already_suspended", "This account is already suspended.")
    return target


def validate_remove_content(report: dict) -> None:
    kind = report["target_type"]
    if kind == "user":
        raise report_error(400, "no_content_to_remove", "A user report has no content to remove.")
    if kind == "event":
        content = _event_of(report)
    else:
        content = _first(
            supabase.table("event_chats").select("id, removed_at").eq("id", report["message_id"]).limit(1).execute()
        )
    # Deleted content counts as removed, like in the report details.
    if content is None or content.get("removed_at"):
        raise report_error(409, "already_removed", "This content is already removed.")


def claim(report_id: int, status_value: str, outcome: str, admin_id: str, claimed_at: str | None = None) -> None:
    """Close the report if it is still open. Nothing comes back when another administrator was first."""
    claimed = (
        supabase.table("reports")
        .update({"status": status_value, "outcome": outcome, "closed_by": admin_id,
                 "closed_at": claimed_at or _now()})
        .eq("id", report_id)
        .eq("status", "open")
        .execute()
    )
    if not claimed.data:
        raise report_error(409, "report_closed", "This report is already closed.")


def revert(report_id: int, status_value: str, admin_id: str, outcome: str | None = None,
           action: str | None = None) -> bool:
    """Reopen the report, but only the closure this administrator made. Never raises.

    Tries REOPEN_ATTEMPTS times (the update is idempotent). A database error counts as a failed attempt,
    also a unique violation of the open-report index (the reporter filed a new open report meanwhile).
    When every attempt fails the report stays falsely closed: that is logged at CRITICAL and written to
    the audit log, so a human can reopen it. Returns True when the reopen went through.
    """
    for attempt in range(1, REOPEN_ATTEMPTS + 1):
        try:
            (
                supabase.table("reports")
                .update({"status": "open", "outcome": None, "closed_by": None, "closed_at": None})
                .eq("id", report_id)
                .eq("status", status_value)
                .eq("closed_by", admin_id)
                .execute()
            )
            return True
        except Exception:
            logger.error("Could not reopen report %s (attempt %s of %s)", report_id, attempt, REOPEN_ATTEMPTS,
                         exc_info=True)
    logger.critical("Report %s stays closed (%s) although its action failed: it could not be reopened",
                    report_id, outcome or status_value, exc_info=True)
    record_audit(
        action="report_close_unreverted",
        admin_id=admin_id,
        entity_type="report",
        entity_id=str(report_id),
        description=f"Report {report_id} is closed but its action failed and it could not be reopened",
        details={"outcome": outcome or status_value, "action": action or "none"},
    )
    return False


def _translate(error: HTTPException, known: dict) -> HTTPException:
    """The reused services raise plain-string details; the report endpoints use coded ones."""
    if isinstance(error.detail, str):
        coded = known.get((error.status_code, error.detail))
        if coded is not None:
            return report_error(error.status_code, *coded)
    return error


_WARN_ERRORS = {
    (404, "User not found."): ("reported_user_not_found", "The reported user no longer exists."),
    (400, "Administrator accounts cannot be warned."):
        ("reported_user_is_administrator", "Administrator accounts cannot be warned."),
}
_SUSPEND_ERRORS = {
    (404, "User not found."): ("reported_user_not_found", "The reported user no longer exists."),
    (400, "Administrator accounts cannot be suspended."):
        ("reported_user_is_administrator", "Administrator accounts cannot be suspended."),
    (409, "This account is already suspended."): ("already_suspended", "This account is already suspended."),
}


def run_warn(report: dict, target: dict, admin_id: str, reason: str) -> None:
    about_type, about_id = _about(report)
    try:
        give_warning(target["id"], admin_id, reason, about_type, about_id)
    except HTTPException as e:
        # A race between the validation and the service (target promoted, deleted ...).
        translated = _translate(e, _WARN_ERRORS)
        if translated is e:
            raise
        raise translated from e


def run_suspend(target: dict, admin_id: str, reason: str) -> None:
    try:
        suspend_user(target["id"], admin_id, reason)
    except HTTPException as e:
        translated = _translate(e, _SUSPEND_ERRORS)
        if translated is e:
            raise
        raise translated from e


def run_remove_content(report: dict, admin_id: str, background_tasks) -> None:
    if report["target_type"] == "event":
        remove_event(report["event_id"], admin_id, report_id=report["id"], background_tasks=background_tasks)
    else:
        remove_message(report["event_id"], report["message_id"], admin_id, report_id=report["id"])


def _at_or_after(value, moment: str) -> bool:
    def parse(raw) -> datetime:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return parse(value) >= parse(moment)


def _warning_was_given(report: dict, target: dict, admin_id: str, claimed_at: str) -> bool:
    """Is there a warning from THIS administrator for this item, written since this request claimed the
    report? give_warning stamps warnings.created_at with the same ISO UTC format as claimed_at."""
    about_type, about_id = _about(report)
    res = (
        supabase.table("warnings").select("id")
        .eq("user_id", target["id"]).eq("about_type", about_type).eq("about_id", about_id)
        .eq("admin_id", admin_id).gte("created_at", claimed_at)
        .limit(1).execute()
    )
    return bool(res.data)


def _content_was_removed(report: dict, admin_id: str, claimed_at: str) -> bool:
    """Is the event / message marked removed by THIS administrator since this request claimed the report?"""
    if report["target_type"] == "event":
        table, row_id = "events", report["event_id"]
    else:
        table, row_id = "event_chats", report["message_id"]
    row = _first(supabase.table(table).select("id, removed_at, removed_by").eq("id", row_id).limit(1).execute())
    if not row or not row.get("removed_at"):
        return False
    return str(row.get("removed_by")).lower() == str(admin_id).lower() and _at_or_after(row["removed_at"], claimed_at)


def _is_removal_incomplete(exc: BaseException) -> bool:
    return (isinstance(exc, HTTPException) and isinstance(exc.detail, dict)
            and exc.detail.get("code") == "removal_incomplete")


def _close(report: dict, status_value: str, outcome: str, admin_id: str, action: str, run,
           effect_check=None) -> str:
    """Claim, run the service, and reopen the report when the service fails. Returns the claim's timestamp.

    The reused services are not atomic: they can raise after their work is committed. effect_check(claimed_at)
    tells whether it is (True) or not (False); None means a failure cannot leave an effect (suspension).
      * effect present: keep the report closed, log the original error, carry on as a success; except
        removal_incomplete (removed, owner not warned, removal not undone): the closure is audited
        with removal:incomplete and the error is raised unchanged, so the administrator sees it;
      * effect absent: reopen and raise the original error;
      * check itself fails: unknown. Reopening could let a retry repeat a committed action, keeping it
        closed hides a failed one; the report stays closed (a retry gets 409, nothing is repeated), the
        failure is CRITICAL + audited for a human, and the original error is raised.
    """
    report_id = report["id"]
    claimed_at = _now()
    try:
        claim(report_id, status_value, outcome, admin_id, claimed_at)
    except HTTPException:
        raise    # lost the race: nothing of ours was written, nothing to undo
    except Exception:
        # e.g. the response got lost after the server applied the update; the guarded reopen is idempotent
        revert(report_id, status_value, admin_id, outcome, action)
        raise
    try:
        run()
    except BaseException as exc:
        state = "absent"
        if effect_check is not None:
            try:
                state = "present" if effect_check(claimed_at) else "absent"
            except Exception:
                state = "unknown"
                logger.error("Could not check whether the action of report %s was done", report_id,
                             exc_info=True)
        if state == "absent":
            revert(report_id, status_value, admin_id, outcome, action)
            raise
        if state == "present":
            logger.error("Report %s: the action was done but the service raised afterwards; "
                         "the report stays closed", report_id, exc_info=exc)
            if _is_removal_incomplete(exc):
                record_audit(
                    action="report_action_taken",
                    admin_id=admin_id,
                    entity_type="report",
                    entity_id=str(report_id),
                    description=f"Acted on report {report_id}: {outcome}; the owner was not warned",
                    details={"outcome": outcome, "action": action, "removal": "incomplete"},
                )
                raise
            if not isinstance(exc, Exception):
                raise
        else:
            logger.critical("Report %s is closed and it is unknown whether its action was done; "
                            "it is NOT reopened: reconcile it by hand", report_id, exc_info=exc)
            record_audit(
                action="report_close_unreverted",
                admin_id=admin_id,
                entity_type="report",
                entity_id=str(report_id),
                description=f"Report {report_id} is closed; its action failed with an unknown result",
                details={"outcome": outcome, "action": action, "effect": "unknown"},
            )
            raise
    return claimed_at


def _person_ref(user_id) -> dict | None:
    return {"id": str(user_id)} if user_id else None


def _fallback_details(report: dict, status_value: str, outcome: str, admin_id: str, closed_at: str,
                      content_removed: bool) -> dict:
    """The body of AdminReportDetailResponse built from the report row loaded before the action plus what
    the action established, for when the details cannot be loaded. Best known, not live: people and the
    event card carry only their ids (title, names, avatars are null), content_removed is true only for
    a removal and reported_user_is_administrator is false."""
    target = report["target_type"]
    event_ref = {"id": str(report["event_id"])} if report.get("event_id") else None
    from_chat = report.get("origin") == "event_chat"
    return {
        "id": report["id"],
        "status": status_value,
        "reason": report["reason"],
        "created_at": str(report["created_at"]),
        "target_type": target,
        "origin": report["origin"],
        "reporter": _person_ref(report.get("reporter_id")),
        "reported": {
            "type": target,
            "event": event_ref if target == "event" else None,
            "user": _person_ref(report.get("reported_user_id")) if target != "event" else None,
            "message": ({"id": report["message_id"], "event_id": event_ref and event_ref["id"]}
                        if target == "message" else None),
        },
        "description": report.get("description"),
        "event": event_ref if from_chat else None,
        "chat_context": report.get("chat_context") if from_chat else None,
        "outcome": outcome,
        "closed_by": _person_ref(admin_id),
        "closed_at": closed_at,
        "content_removed": content_removed,
        "reported_user_is_administrator": False,
    }


def _details_after_close(report: dict, status_value: str, outcome: str, admin_id: str, closed_at: str,
                         content_removed: bool = False) -> dict:
    """get_report_details, tried twice. The action is done by now, so a failure to LOAD it must not turn
    the success into a 500: the second failure answers with the fallback body."""
    for attempt in (1, 2):
        try:
            return get_report_details(report["id"])
        except Exception:
            logger.error("Could not load the details of report %s after closing it (attempt %s of 2)",
                         report["id"], attempt, exc_info=True)
    return _fallback_details(report, status_value, outcome, admin_id, closed_at, content_removed)


def dismiss_report(report_id: int, admin_id: str) -> dict:
    report = load_report(report_id)
    claimed_at = _now()
    try:
        claim(report["id"], "dismissed", "dismissed", admin_id, claimed_at)
    except HTTPException:
        raise
    except Exception:
        revert(report["id"], "dismissed", admin_id, "dismissed", "dismiss")
        raise
    record_audit(
        action="report_dismissed",
        admin_id=admin_id,
        entity_type="report",
        entity_id=report_id,
        description=f"Dismissed report {report_id}",
        details={"outcome": "dismissed"},
    )
    return _details_after_close(report, "dismissed", "dismissed", admin_id, claimed_at)


def act_on_report(report_id: int, admin_id: str, action: str, reason: str | None, background_tasks=None) -> dict:
    report = load_report(report_id)
    outcome = _OUTCOMES[action]
    if action == "warn":
        target = validate_warn(report)
        run = lambda: run_warn(report, target, admin_id, reason)
        effect = lambda claimed_at: _warning_was_given(report, target, admin_id, claimed_at)
    elif action == "suspend":
        target = validate_suspend(report)
        run = lambda: run_suspend(target, admin_id, reason)
        effect = None   # suspend_user cannot fail after its commit point (the profile update)
    else:
        validate_remove_content(report)
        run = lambda: run_remove_content(report, admin_id, background_tasks)
        effect = lambda claimed_at: _content_was_removed(report, admin_id, claimed_at)

    claimed_at = _close(report, "action_taken", outcome, admin_id, action, run, effect)
    record_audit(
        action="report_action_taken",
        admin_id=admin_id,
        entity_type="report",
        entity_id=report_id,
        description=f"Acted on report {report_id}: {outcome}",
        details={"outcome": outcome, "action": action},
    )
    return _details_after_close(report, "action_taken", outcome, admin_id, claimed_at,
                                content_removed=action == "remove_content")
