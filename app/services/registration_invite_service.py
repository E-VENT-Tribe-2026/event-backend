import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from pydantic import EmailStr

from app.core.config import settings
from app.db.supabase_client import supabase

logger = logging.getLogger(__name__)

INVITE_TTL = timedelta(days=7)
INVITE_CODE_LENGTH = 8
INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
INVALID_INVITE = "A valid invitation code is required to register."


def normalize_invite_email(email: str) -> str:
    return str(email or "").strip().lower()


def normalize_invite_code(code: str) -> str:
    return "".join(ch for ch in str(code or "").upper() if ch.isalnum())


def format_invite_code(code: str) -> str:
    compact = normalize_invite_code(code)
    if len(compact) == INVITE_CODE_LENGTH:
        return f"{compact[:4]}-{compact[4:]}"
    return compact


def hash_invite_code(code: str) -> str:
    return hashlib.sha256(normalize_invite_code(code).encode("utf-8")).hexdigest()


def generate_invite_code() -> str:
    return "".join(secrets.choice(INVITE_ALPHABET) for _ in range(INVITE_CODE_LENGTH))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _invite_error(detail: str = INVALID_INVITE) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _open_invite_for_email(email: str) -> dict | None:
    res = (
        supabase.table("registration_invites")
        .select("id, email, code_hash, expires_at, used_at")
        .eq("email", email)
        .is_("used_at", "null")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


def require_registration_invite(email: str, code: str) -> dict:
    """Return the unused, unexpired invite for this email and code, or raise."""
    normalized_email = normalize_invite_email(email)
    normalized_code = normalize_invite_code(code)
    if not normalized_email or len(normalized_code) != INVITE_CODE_LENGTH:
        raise _invite_error()

    row = _open_invite_for_email(normalized_email)
    if not row:
        raise _invite_error()

    expires_at = row.get("expires_at")
    if expires_at:
        try:
            expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if expiry <= _now():
                raise _invite_error()
        except HTTPException:
            raise
        except Exception:
            raise _invite_error()

    if row.get("code_hash") != hash_invite_code(normalized_code):
        raise _invite_error()
    return row


def mark_registration_invite_used(invite_id, user_id: str) -> None:
    try:
        supabase.table("registration_invites").update({
            "used_at": _now().isoformat(),
            "used_by": user_id,
        }).eq("id", invite_id).execute()
    except Exception as e:
        logger.error(f"Could not mark registration invite {invite_id} used: {e}")


def verify_registration_invite(email: str, code: str) -> dict:
    require_registration_invite(email, code)
    return {"valid": True, "email": normalize_invite_email(email)}


def send_registration_invite(admin_id: str, email: EmailStr | str) -> dict:
    """Create or refresh a signup invite and email the code to the invited person."""
    normalized_email = normalize_invite_email(str(email))
    if not normalized_email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email is required.")

    code = generate_invite_code()
    expires_at = _now() + INVITE_TTL
    payload = {
        "email": normalized_email,
        "code_hash": hash_invite_code(code),
        "invited_by": admin_id,
        "expires_at": expires_at.isoformat(),
        "used_at": None,
        "used_by": None,
    }

    existing = _open_invite_for_email(normalized_email)
    try:
        if existing:
            supabase.table("registration_invites").update(payload).eq("id", existing["id"]).execute()
            invite_id = existing["id"]
        else:
            inserted = supabase.table("registration_invites").insert(payload).execute()
            invite_id = (inserted.data or [{}])[0].get("id")
    except Exception as e:
        logger.error(f"Could not save registration invite for {normalized_email}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create the invitation.",
        )

    formatted = format_invite_code(code)
    from app.services.email_service import send_email, build_registration_invite_email
    subject, plain, html = build_registration_invite_email(formatted, expires_at)
    send_email(normalized_email, subject, plain, html)

    try:
        from app.services.audit_service import record_audit
        record_audit(
            action="registration_invite",
            admin_id=admin_id,
            entity_type="registration_invite",
            entity_id=str(invite_id or normalized_email),
            description=f"Sent a registration invitation to {normalized_email}.",
            details={"email": normalized_email},
        )
    except Exception as e:
        logger.error(f"Could not audit registration invite for {normalized_email}: {e}")

    return {
        "email": normalized_email,
        "code": formatted,
        "expires_at": expires_at.isoformat(),
        "message": "Invitation email sent. The invited person must enter this code to register.",
    }
