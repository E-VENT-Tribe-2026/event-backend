from fastapi import HTTPException, status
from openai import APIError
from app.db.supabase_client import supabase
from gotrue.errors import AuthApiError
from app.utils.embedding_helper import generate_embedding
from app.core.config import settings
import httpx


def register_user(
    email: str, 
    password: str, 
    dob: str,
    gender: str, 
    interests: list[str],
    full_name: str | None = None
):
    try:
        auth_response = supabase.auth.sign_up({
            "email": email,
            "password": password,
            "options": {
                "data": {
                    "full_name": full_name
                }
            }
        })

        if not auth_response.user:
            raise HTTPException(status_code=400, detail="Registration failed")

        user_id = auth_response.user.id

        # Generate interest embedding
        interest_embedding = None
        if interests:
            embedding_text = " ".join(interests)
            interest_embedding = generate_embedding(embedding_text)

        profile_data = {
            "dob": dob,
            "gender": gender,
            "interests": interests,
            "full_name": full_name,
        }

        if interest_embedding:
            profile_data["interest_embedding"] = interest_embedding

        profile_response = (
            supabase.table("profiles")
            .update(profile_data)
            .eq("id", user_id)
            .execute()
        )

        if auth_response.session is None:
            return {"message": "User registered. Please confirm email to activate profile."}

        return {
            "access_token": auth_response.session.access_token,
            "user_id": user_id,
            "data": profile_response.data
        }

    except AuthApiError as e:
        raise HTTPException(status_code=400, detail=f"Auth Error: {str(e)}")
    
    except APIError as e:
        if "age_18_or_older" in str(e):
            raise HTTPException(
                status_code=400, 
                detail="Registration blocked: You must be 18 or older."
            )
        raise HTTPException(status_code=400, detail=f"Database Error: {str(e)}")
    
    
from gotrue.errors import AuthApiError

def login_user(email: str, password: str):
    try:
        response = supabase.auth.sign_in_with_password({
            "email": email,
            "password": password
        })

        if response.session is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email not confirmed. Please check your inbox."
            )

        return {
            "access_token": response.session.access_token,
            "token_type": "bearer"
        }

    except AuthApiError as e:
        error = str(e).lower()

        if "invalid login credentials" in error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password."
            )
        if "email not confirmed" in error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email not confirmed. Please check your inbox."
            )
        if "too many requests" in error:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many login attempts. Please wait a moment and try again."
            )

        # Fallback for any other auth error
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )


def request_password_reset(email: str):
    """
    Step 1: Check the email exists via the admin API, then trigger Supabase reset email.
    """
    # Check whether the email is registered using the admin users list endpoint
    url = f"{settings.SUPABASE_URL}/auth/v1/admin/users"
    headers = {
        "apikey": settings.SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
    }

    try:
        resp = httpx.get(url, headers=headers, params={"email": email}, timeout=10)
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to reach authentication service. Please try again later."
        )

    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to verify email. Please try again later."
        )

    users = resp.json().get("users", [])
    # Filter exact match
    matched = [u for u in users if u.get("email", "").lower() == email.lower()]

    if not matched:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email not registered."
        )

    # Email exists — trigger the Supabase reset email
    try:
        supabase.auth.reset_password_email(
            email,
            {
                "redirect_to": f"{settings.FRONTEND_URL}/reset-password"
            }
        )
    except AuthApiError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to send reset email: {str(e)}"
        )

    return {"message": "Password reset email sent."}


def reset_password(access_token: str, new_password: str):
    """
    Step 2: Validate the reset token from the email link and update the password.
    """
    try:
        user_response = supabase.auth.get_user(access_token)
    except AuthApiError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired reset link."
        )

    if not user_response or not user_response.user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired reset link."
        )

    user_id = user_response.user.id

    url = f"{settings.SUPABASE_URL}/auth/v1/admin/users/{user_id}"
    headers = {
        "apikey": settings.SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
    }

    try:
        resp = httpx.put(url, headers=headers, json={"password": new_password}, timeout=10)
    except httpx.RequestError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to reach authentication service. Please try again later."
        )

    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Password update failed: {resp.text}"
        )

    return {"message": "Password updated successfully."}


def change_password(email: str, user_id: str, current_password: str, new_password: str):
    if current_password == new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password cannot be the same as the previous/current password."
        )

    try:
        # Verify the current password by signing in
        verify_response = supabase.auth.sign_in_with_password({
            "email": email,
            "password": current_password
        })

        if verify_response.session is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect current password."
            )

        # Update password via REST admin API using the service key
        url = f"{settings.SUPABASE_URL}/auth/v1/admin/users/{user_id}"
        headers = {
            "apikey": settings.SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
            "Content-Type": "application/json",
        }
        resp = httpx.put(url, headers=headers, json={"password": new_password}, timeout=10)

        if resp.status_code != 200:
            raise HTTPException(status_code=400, detail=f"Password update failed: {resp.text}")

        return {"message": "Password updated successfully."}

    except AuthApiError as e:
        error = str(e).lower()
        if "invalid login credentials" in error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect current password."
            )
        raise HTTPException(status_code=400, detail=f"Auth Error: {str(e)}")