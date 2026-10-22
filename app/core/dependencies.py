import base64
import json
import logging
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.db.supabase_client import supabase

logger = logging.getLogger(__name__)

security = HTTPBearer()
optional_security = HTTPBearer(auto_error=False)

def suspension_error(reason: str | None) -> HTTPException:
    """403 for a suspended account (#192). Only sent once the credentials or session are valid."""
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "account_suspended",
            "message": "Your account is suspended.",
            "reason": reason,
        },
    )


def refuse_if_suspended(user_id: str) -> None:
    """Raise suspension_error when the account is suspended (#192)."""
    try:
        res = (
            supabase.table("profiles")
            .select("suspended_at, suspension_reason")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        data = res.data
    except Exception as e:
        logger.error(f"Could not check suspension of user {user_id}: {e}")
        return
    if isinstance(data, list):
        data = data[0] if data else {}
    if isinstance(data, dict) and data.get("suspended_at"):
        raise suspension_error(data.get("suspension_reason"))


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    The signed-in user. Every authenticated endpoint depends on this (directly or through
    require_regular_user, get_current_onboarded_user or require_admin), so a suspended
    account is refused here on every request, whichever way it signed in (#192).
    """
    token = credentials.credentials

    try:
        user = supabase.auth.get_user(token)

        if user.user is None:
            raise HTTPException(status_code=401, detail="Invalid token")

    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    refuse_if_suspended(user.user.id)
    return user.user


def get_optional_user(credentials: HTTPAuthorizationCredentials | None = Depends(optional_security)):
    """For public endpoints: the signed-in user when a valid token is sent, otherwise None.
    A suspended account's token is refused, not treated as anonymous (#192)."""
    if credentials is None:
        return None
    try:
        result = supabase.auth.get_user(credentials.credentials)
        user = result.user
    except Exception:
        return None
    if user is not None:
        refuse_if_suspended(user.id)
    return user

def require_regular_user(user=Depends(get_current_user)):
    """
    Ensures that the authenticated user is NOT an administrator.
    Administrator accounts are strictly separated from user functions.
    """
    try:
        result = (
            supabase.table("profiles")
            .select("role")
            .eq("id", user.id)
            .single()
            .execute()
        )
        role = (result.data or {}).get("role")
    except Exception:
        role = None

    if role in ("administrator", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator accounts cannot perform user actions.",
        )

    return user


def _profile_row(user_id: str, columns: str) -> dict:
    result = (
        supabase.table("profiles")
        .select(columns)
        .eq("id", user_id)
        .single()
        .execute()
    )
    return result.data or {}


def is_admin_role(role) -> bool:
    return str(role or "").lower() in ("administrator", "admin")


def get_own_profile_user(user=Depends(get_current_user)):
    """Admins may read their own profile after MFA; regular users still need onboarding."""
    data = {}
    for columns in ("username, full_name, role", "username, full_name"):
        try:
            data = _profile_row(user.id, columns)
            break
        except Exception:
            data = {}

    if is_admin_role(data.get("role")):
        return user

    username = (data.get("username") or "").strip()
    full_name = (data.get("full_name") or "").strip()
    if not username or not full_name:
        raise HTTPException(
            status_code=403,
            detail="Profile setup required: please choose a username and enter your full name.",
        )
    return user


def get_current_onboarded_user(user=Depends(require_regular_user)):
    """Extends require_regular_user by requiring a completed profile (username + full_name)."""
    data = {}
    for columns in ("username, full_name, role", "username, full_name"):
        try:
            result = (
                supabase.table("profiles")
                .select(columns)
                .eq("id", user.id)
                .single()
                .execute()
            )
            data = result.data or {}
            break
        except Exception:
            data = {}

    role = data.get("role")
    if role in ("administrator", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator accounts cannot perform user actions.",
        )

    username = (data.get("username") or "").strip()
    full_name = (data.get("full_name") or "").strip()

    if not username or not full_name:
        raise HTTPException(
            status_code=403,
            detail="Profile setup required: please choose a username and enter your full name.",
        )

    return user


def jwt_claims(token: str) -> dict:
    """Read claims from a JWT without verifying the signature (middleware already did)."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Malformed token")
    padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
    claims = json.loads(base64.urlsafe_b64decode(padded))
    if not isinstance(claims, dict):
        raise ValueError("Malformed token")
    return claims


def token_is_mfa_verified(token: str) -> bool:
    """True when this sign-in has completed TOTP MFA (aal2, or amr includes totp)."""
    try:
        claims = jwt_claims(token)
    except Exception:
        return False
    if str(claims.get("aal") or "").lower() == "aal2":
        return True
    amr = claims.get("amr") or []
    for entry in amr:
        method = entry.get("method") if isinstance(entry, dict) else entry
        if str(method or "").lower() in {"totp", "mfa"}:
            return True
    return False


def require_admin(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    user = Depends(get_current_user)
):
    """
    Check for administrative endpoints:
    1. Authenticity of the token is checked by Supabase (supabase.auth.get_user).
    2. The user holds the 'administrator' role in public.profiles.
    3. The current sign-in has been verified via MFA (AAL level is 'aal2').
    Refuses any request that fails either check, including direct API requests or forged tokens.
    """
    token = credentials.credentials

    # 1. Fetch user's role from profiles
    try:
        profile_res = (
            supabase.table("profiles")
            .select("role")
            .eq("id", user.id)
            .single()
            .execute()
        )
        role = (profile_res.data or {}).get("role")
    except Exception as e:
        logger.error(f"require_admin failed to fetch profile for user {user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Could not verify administrator role."
        )

    if not is_admin_role(role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Administrative privileges required."
        )

    # 2. Check token AAL / AMR for a verified authenticator sign-in
    try:
        jwt_claims(token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or malformed token."
        )

    if not token_is_mfa_verified(token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Administrator sign-in verification required. Please complete MFA."
        )

    return user