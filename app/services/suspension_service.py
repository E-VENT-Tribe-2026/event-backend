"""Suspending accounts and lifting suspensions (#192).

An account is suspended while profiles.suspended_at is not null. Suspending deletes nothing.
Refusing the suspended account's requests happens in app.core.dependencies (every request)
and app.services.auth_service.login_user (sign-in).
"""
import logging
from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.db.supabase_client import supabase
from app.services.admin_service import end_upcoming_activity
from app.services.audit_service import record_audit

logger = logging.getLogger(__name__)

SUSPENSION_CANCELLATION_REASON = "Organizer's account was suspended"


def _load_user(user_id: str) -> dict:
    res = (
        supabase.table("profiles")
        .select("id, role, suspended_at, suspension_reason")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return res.data[0]


def _suspension_effects_incomplete(user_id: str, suspended_since) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "suspension_effects_incomplete",
            "message": (
                "The account is suspended, but required event updates could not be completed. "
                "Retry this request after the database recovers."
            ),
            "user_id": user_id,
            "status": "suspended",
            "suspended_since": suspended_since,
        },
    )


def _end_upcoming_activity(user_id: str, suspended_since) -> tuple[int, int]:
    try:
        return end_upcoming_activity(
            user_id,
            cancellation_reason=SUSPENSION_CANCELLATION_REASON,
            notification_text="Event '{title}' was cancelled because the organizer's account was suspended",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Could not apply suspension event effects for user {user_id}: {e}")
        raise _suspension_effects_incomplete(user_id, suspended_since)


def suspend_user(user_id: str, admin_id: str, reason: str) -> dict:
    profile = _load_user(user_id)
    if profile.get("role") in ("administrator", "admin"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Administrator accounts cannot be suspended.")

    already_suspended = bool(profile.get("suspended_at"))
    now = datetime.now(timezone.utc).isoformat()
    suspended_since = profile.get("suspended_at") or now

    if not already_suspended:
        # Suspend first: from this moment every request of the account is refused.
        updated = (
            supabase.table("profiles")
            .update({"suspended_at": now, "suspension_reason": reason})
            .eq("id", user_id)
            .is_("suspended_at", "null")      # two administrators at once: only the first one wins
            .execute()
        )
        if not updated.data:
            # Lost a concurrent suspend: the account is already marked. Finish leftover effects.
            already_suspended = True
            reloaded = _load_user(user_id)
            suspended_since = reloaded.get("suspended_at") or now
        else:
            suspended_since = now

    # Required event effects. If they fail, the account stays suspended and this
    # endpoint can be retried to finish them (do not 409 until they are complete).
    cancelled, removed = _end_upcoming_activity(user_id, suspended_since)

    if already_suspended and cancelled == 0 and removed == 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="This account is already suspended.")

    record_audit(
        action="account_suspended",
        admin_id=admin_id,
        entity_type="user",
        entity_id=user_id,
        description=f"Suspended user {user_id}: {reason}",
        details={"reason": reason, "cancelled_events_count": cancelled,
                 "joined_events_removed_count": removed,
                 "retried": already_suspended},
    )

    return {"user_id": user_id, "status": "suspended", "suspended_since": suspended_since,
            "cancelled_events_count": cancelled, "joined_events_removed_count": removed}


def lift_suspension(user_id: str, admin_id: str, reason: str) -> dict:
    profile = _load_user(user_id)
    if not profile.get("suspended_at"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="This account is not suspended.")

    # Restores the account. Does not re-add events or reopen cancelled events or chats.
    supabase.table("profiles") \
        .update({"suspended_at": None, "suspension_reason": None}) \
        .eq("id", user_id).execute()

    record_audit(
        action="suspension_lifted",
        admin_id=admin_id,
        entity_type="user",
        entity_id=user_id,
        description=f"Lifted the suspension of user {user_id}: {reason}",
        details={"reason": reason, "suspended_since": profile.get("suspended_at")},
    )

    _send_lifted_email(user_id)

    return {"user_id": user_id, "status": "active", "suspended_since": None,
            "cancelled_events_count": 0, "joined_events_removed_count": 0}


def _send_lifted_email(user_id: str) -> None:
    """Best effort: if the email fails, lifting the suspension still succeeds."""
    try:
        from app.services.reminder_service import _get_user_email
        from app.services.email_service import send_email

        email = _get_user_email(user_id)
        if not email:
            logger.warning(f"No email found for user {user_id}; suspension lifted without email.")
            return
        send_email(
            email,
            "Your E-VENT account is active again",
            "The suspension of your E-VENT account has been lifted. You can sign in again.\n\n"
            "Events that were cancelled or left while your account was suspended stay as they are.",
        )
    except Exception as e:
        logger.error(f"Could not send the suspension-lifted email to user {user_id}: {e}")