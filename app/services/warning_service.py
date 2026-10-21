"""Warnings an administrator gives a user (#191).

A warning COUNTS while withdrawn_at is null.
A warning WAITS to be acknowledged while acknowledged_at and withdrawn_at are both null.
"""
import logging
from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.db.supabase_client import supabase
from app.services.audit_service import record_audit, _people

logger = logging.getLogger(__name__)

WARNING_NOTIFICATION_TYPE = "warning"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _about(row: dict):
    if row.get("about_type") and row.get("about_id"):
        return {"type": row["about_type"], "id": row["about_id"]}
    return None


def _get_warning(warning_id: int) -> dict:
    res = supabase.table("warnings").select("*").eq("id", warning_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Warning not found.")
    return res.data[0]


# ---- counting (used by the user list and user details too) -----------------

def counted_warning_counts(user_ids: list) -> dict:
    """{user_id: number of warnings that count} for the given users, in one query."""
    ids = [u for u in user_ids if u]
    if not ids:
        return {}
    res = (
        supabase.table("warnings")
        .select("user_id")
        .in_("user_id", ids)
        .is_("withdrawn_at", "null")
        .execute()
    )
    counts = {u: 0 for u in ids}
    for row in res.data or []:
        counts[row["user_id"]] = counts.get(row["user_id"], 0) + 1
    return counts


def user_ids_with_counted_warnings() -> list:
    res = supabase.table("warnings").select("user_id").is_("withdrawn_at", "null").execute()
    return list(dict.fromkeys(row["user_id"] for row in (res.data or [])))


# ---- administrator actions --------------------------------------------------

def give_warning(user_id: str, admin_id: str, reason: str,
                 about_type: str | None = None, about_id: str | None = None) -> dict:
    prof = supabase.table("profiles").select("id, role").eq("id", user_id).limit(1).execute()
    if not prof.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if prof.data[0].get("role") in ("administrator", "admin"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Administrator accounts cannot be warned.")

    now = _now()
    # 1. The warning itself. If this fails, nothing else is written.
    created = supabase.table("warnings").insert({
        "user_id": user_id,
        "admin_id": admin_id,
        "reason": reason,
        "about_type": about_type,
        "about_id": about_id,
        "created_at": now,
    }).execute()
    warning = created.data[0]

    # 2. The notification. Inserted directly: create_notification() skips "duplicates"
    #    with the same message within 10 seconds, which would drop a second warning.
    try:
        supabase.table("notifications").insert({
            "user_id": user_id,
            "event_id": None,
            "type": WARNING_NOTIFICATION_TYPE,
            "message": reason,
            "is_read": False,
            "warning_id": warning["id"],
            "created_at": now,
        }).execute()
    except Exception as e:
        # The warning still shows through /warnings/pending, so do not fail the request.
        logger.error(f"Could not create the notification for warning {warning['id']}: {e}")

    # 3. The audit log.
    record_audit(
        action="warning_given",
        admin_id=admin_id,
        entity_type="user",
        entity_id=user_id,
        description=f"Warned user {user_id}: {reason}",
        details={"warning_id": warning["id"], "reason": reason,
                 "about": f"{about_type}/{about_id}" if about_type else "none"},
    )

    return warning_to_history_item(warning, _people([admin_id]))


def withdraw_warning(warning_id: int, admin_id: str) -> dict:
    warning = _get_warning(warning_id)
    if warning.get("withdrawn_at"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="This warning has already been withdrawn.")

    now = _now()
    updated = (
        supabase.table("warnings")
        .update({"withdrawn_at": now, "withdrawn_by": admin_id})
        .eq("id", warning_id)
        .is_("withdrawn_at", "null")      # two admins at once: only the first one wins
        .execute()
    )
    if not updated.data:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="This warning has already been withdrawn.")
    warning = updated.data[0]

    record_audit(
        action="warning_withdrawn",
        admin_id=admin_id,
        entity_type="user",
        entity_id=warning["user_id"],
        description=f"Withdrew warning {warning_id} of user {warning['user_id']}",
        details={"warning_id": warning_id, "reason": warning.get("reason")},
    )

    return warning_to_history_item(warning, _people([warning.get("admin_id"), admin_id]))


def get_warning_history(user_id: str) -> dict:
    res = (
        supabase.table("warnings")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    rows = res.data or []
    people = _people([r.get("admin_id") for r in rows] + [r.get("withdrawn_by") for r in rows])
    return {"user_id": user_id, "items": [warning_to_history_item(r, people) for r in rows]}


def warning_to_history_item(row: dict, people: dict) -> dict:
    return {
        "id": row["id"],
        "created_at": row.get("created_at"),
        "reason": row.get("reason"),
        "about": _about(row),
        "given_by": people.get(row.get("admin_id")),
        "is_withdrawn": row.get("withdrawn_at") is not None,
        "withdrawn_at": row.get("withdrawn_at"),
        "withdrawn_by": people.get(row.get("withdrawn_by")),
        "acknowledged_at": row.get("acknowledged_at"),
    }


# ---- user actions -----------------------------------------------------------

def get_pending_warnings(user_id: str) -> dict:
    res = (
        supabase.table("warnings")
        .select("id, created_at, reason, about_type, about_id")
        .eq("user_id", user_id)
        .is_("acknowledged_at", "null")
        .is_("withdrawn_at", "null")
        .order("created_at", desc=False)
        .execute()
    )
    return {"items": [
        {"id": r["id"], "created_at": r.get("created_at"), "reason": r.get("reason"), "about": _about(r)}
        for r in (res.data or [])
    ]}


def acknowledge_warning(warning_id: int, user_id: str) -> dict:
    warning = _get_warning(warning_id)
    if str(warning.get("user_id")) != str(user_id):
        # 404, not 403: do not tell a user that someone else's warning exists.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Warning not found.")

    if warning.get("acknowledged_at"):          # second device, double tap: already done
        return {"id": warning["id"], "acknowledged_at": warning["acknowledged_at"]}

    now = _now()
    supabase.table("warnings").update({"acknowledged_at": now}) \
        .eq("id", warning_id).eq("user_id", user_id).is_("acknowledged_at", "null").execute()

    # Seeing and acknowledging the dialog also reads its notification.
    try:
        supabase.table("notifications").update({"is_read": True}) \
            .eq("user_id", user_id).eq("warning_id", warning_id).execute()
    except Exception as e:
        logger.warning(f"Could not mark the notification of warning {warning_id} as read: {e}")

    return {"id": warning["id"], "acknowledged_at": now}


def warning_states(warning_ids: list) -> dict:
    """{warning_id: row} for the notification list, in one query."""
    ids = [w for w in warning_ids if w is not None]
    if not ids:
        return {}
    res = (
        supabase.table("warnings")
        .select("id, acknowledged_at, withdrawn_at")
        .in_("id", ids)
        .execute()
    )
    return {row["id"]: row for row in (res.data or [])}