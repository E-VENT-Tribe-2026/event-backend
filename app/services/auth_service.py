from fastapi import HTTPException, status
from app.db.supabase_client import supabase
from gotrue.errors import AuthApiError


def _email_already_registered(email: str) -> bool:
    """Check the profiles table for an existing user with this email."""
    response = (
        supabase.table("profiles")
        .select("id")
        .eq("email", email)
        .execute()
    )
    return bool(response.data)


def register_user(email: str, password: str, full_name: str | None = None):
    try:
        response = supabase.auth.sign_up({
            "email": email,
            "password": password,
            "options": {
                "data": {"full_name": full_name}
            }
        })

        # Supabase returns a session-less user with an identities=[] list when
        # the email is already registered (email confirmation flow).
        # We treat this as a duplicate rather than silently succeeding.
        user = response.user
        if user and hasattr(user, "identities") and user.identities == []:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists.",
            )

        if response.session is None:
            return {"message": "User registered. Please confirm your email."}

        return {
            "access_token": response.session.access_token,
            "token_type": "bearer",
        }

    except HTTPException:
        raise

    except AuthApiError as e:
        error_msg = str(e).lower()
        if "rate limit" in error_msg:
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Please try again later.",
            )
        if "already registered" in error_msg or "already exists" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists.",
            )
        raise HTTPException(status_code=400, detail=str(e))


def login_user(email: str, password: str):
    try:
        response = supabase.auth.sign_in_with_password({
            "email": email,
            "password": password,
        })

        if response.session is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials or email not confirmed.",
            )

        return {
            "access_token": response.session.access_token,
            "token_type": "bearer",
        }

    except HTTPException:
        raise

    except AuthApiError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials or email not confirmed.",
        )