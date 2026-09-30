import base64
import json
import logging
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.db.supabase_client import supabase

logger = logging.getLogger(__name__)

security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials

    try:
        user = supabase.auth.get_user(token)

        if user.user is None:
            raise HTTPException(status_code=401, detail="Invalid token")

        return user.user

    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


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

    if role != "administrator":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Administrative privileges required."
        )

    # 2. Check token AAL level for verified sign-in
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Malformed token")
        padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or malformed token."
        )

    if claims.get("aal") != "aal2":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Administrator sign-in verification required. Please complete MFA."
        )

    return user