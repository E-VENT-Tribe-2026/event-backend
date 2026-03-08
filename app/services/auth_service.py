from fastapi import HTTPException, status
from app.db.supabase_client import supabase
from gotrue.errors import AuthApiError

def register_user(email: str, password: str, full_name: str | None = None):
    try:
        response = supabase.auth.sign_up({
            "email": email,
            "password": password
        })

        if response.session is None:
            return {"message": "User registered. Please confirm email."}

        return {
            "access_token": response.session.access_token,
            "token_type": "bearer"
        }

    except AuthApiError as e:
        if "rate limit" in str(e).lower():
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Please try again later."
            )
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )

def login_user(email: str, password: str):
    response = supabase.auth.sign_in_with_password({
        "email": email,
        "password": password
    })

    if response.session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials or email not confirmed"
        )

    return {
        "access_token": response.session.access_token,
        "token_type": "bearer"
    }