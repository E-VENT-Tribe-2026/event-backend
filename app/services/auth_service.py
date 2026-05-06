from fastapi import HTTPException, status
from openai import APIError
from app.db.supabase_client import supabase
from gotrue.errors import AuthApiError
from app.utils.embedding_helper import generate_embedding
from app.core.config import settings


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
    Step 1: Validate email exists + send reset email
    """

    try:
        # Try sending reset email (Supabase handles existence internally)
        supabase.auth.reset_password_email(
            email,
            {
                "redirect_to": f"{settings.FRONTEND_URL}/reset-password"
            }
        )

        return {"message": "Password reset email sent."}

    except AuthApiError as e:
        error_msg = str(e).lower()

        if "user not found" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Email not registered."
            )

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Auth Error: {str(e)}"
        )


def verify_reset_token(token_hash: str):
    """
    Step 1.5: Exchange the OTP token_hash from the email link for a JWT access_token.
    The frontend calls this instead of parsing the URL hash fragment.
    """

    try:
        response = supabase.auth.verify_otp({
            "token_hash": token_hash,
            "type": "recovery"
        })

        if not response.session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired reset token."
            )

        return {
            "access_token": response.session.access_token,
            "message": "Token verified. Use the access_token to reset your password."
        }

    except AuthApiError as e:
        error_msg = str(e).lower()
        print(f"[verify_reset_token] AuthApiError: {e}")

        if "token has expired" in error_msg or "otp has expired" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Reset token has expired. Please request a new password reset."
            )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired reset token."
        )
    except Exception as e:
        print(f"[verify_reset_token] Unexpected error ({type(e).__name__}): {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired reset token."
        )


def reset_password(access_token: str, new_password: str):
    """
    Step 2: Validate token + update password.
    The access_token is a JWT returned by verify_reset_token.
    We decode it to extract the user ID, then update via admin.
    """
    import json
    import base64
    from supabase import create_client

    try:
        # Decode JWT payload (middle segment) to get user ID
        # JWT format: header.payload.signature
        parts = access_token.split(".")
        if len(parts) != 3:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token format."
            )

        # Add padding if needed and decode
        payload = parts[1]
        payload += "=" * (4 - len(payload) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload))

        user_id = decoded.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token: no user ID found."
            )

        # Create a fresh admin client to ensure we have service role privileges
        # because the global supabase client's session might have been mutated
        # by verify_otp or login operations.
        admin_client = create_client(
            settings.SUPABASE_URL,
            settings.SUPABASE_SERVICE_KEY
        )

        # Update password using admin privileges
        admin_client.auth.admin.update_user_by_id(
            user_id,
            {"password": new_password}
        )

        return {"message": "Password updated successfully."}

    except HTTPException:
        raise
    except AuthApiError as e:
        print(f"[reset_password] AuthApiError: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired reset link."
        )
    except Exception as e:
        print(f"[reset_password] Unexpected error ({type(e).__name__}): {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired reset link."
        )

def change_password(email: str, user_id: str, current_password: str, new_password: str):
    if current_password == new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password cannot be the same as the previous/current password."
        )

    try:
        from supabase import create_client
        # Verify the current password by trying to log in.
        # This will mutate the global client's session.
        verify_response = supabase.auth.sign_in_with_password({
            "email": email,
            "password": current_password
        })

        if verify_response.session is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect current password."
            )

        # Proceed to update the password using the admin client
        # Create a fresh admin client to avoid using the mutated global client
        admin_client = create_client(
            settings.SUPABASE_URL,
            settings.SUPABASE_SERVICE_KEY
        )
        
        admin_client.auth.admin.update_user_by_id(
            user_id,
            {"password": new_password}
        )
        
        # Optionally sign out the global client to prevent leaking the session
        supabase.auth.sign_out()
        
        return {"message": "Password updated successfully."}

    except AuthApiError as e:
        error = str(e).lower()
        if "invalid login credentials" in error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect current password."
            )
        raise HTTPException(status_code=400, detail=f"Auth Error: {str(e)}")