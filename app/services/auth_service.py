from fastapi import HTTPException, status
from postgrest.exceptions import APIError
from app.db.supabase_client import supabase
from gotrue.errors import AuthApiError
from app.utils.embedding_helper import generate_embedding
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)


from app.utils.validators import validate_username, validate_full_name


def register_user(
    email: str, 
    password: str, 
    dob: str,           
    gender: str, 
    interests: list[str],
    full_name: str | None = None,
    username: str | None = None
):
    valid_username = validate_username(username)
    valid_full_name = validate_full_name(full_name)

    # Check if username is already in use
    existing_profile = (
        supabase.table("profiles")
        .select("id")
        .eq("username", valid_username)
        .execute()
    )
    if existing_profile.data and len(existing_profile.data) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username is unavailable. That username is already in use."
        )

    try:
        auth_response = supabase.auth.sign_up({
            "email": email,
            "password": password,
            "options": {
                "data": {
                    "full_name": valid_full_name,
                    "username": valid_username
                }
            }
        })

        if not auth_response.user:
            raise HTTPException(status_code=400, detail="Registration failed")

        if auth_response.user.identities is not None and len(auth_response.user.identities) == 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email address is unavailable. That email address is already in use. User already exists."
            )

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
            "full_name": valid_full_name,
            "username": valid_username,
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
        error = str(e).lower()
        logger.error(f"register_user AuthApiError: {e}")
        if "user already registered" in error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email address is unavailable. That email address is already in use."
            )
        raise HTTPException(status_code=400, detail="Registration failed. Please try again.")

    except APIError as e:
        if "age_18_or_older" in str(e):
            raise HTTPException(
                status_code=400,
                detail="Registration blocked: You must be 18 or older."
            )
        if "profiles_username_key" in str(e) or ("username" in str(e).lower() and "unique" in str(e).lower()):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username is unavailable. That username is already in use."
            )
        logger.error(f"register_user APIError: {e}")
        raise HTTPException(status_code=400, detail="Registration failed due to a server error.")
    
    
from gotrue.errors import AuthApiError

def login_user(email: str, password: str):
    try:
        response = supabase.auth.sign_in_with_password({
            "email": email,
            "password": password
        })

        if response.session is None:
            logger.warning("login_user: sign-in succeeded but session is None (likely unconfirmed email) for email=%s", email)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Login failed. Please check your credentials."
            )

        user_id = response.user.id
        role = None
        try:
            profile_res = (
                supabase.table("profiles")
                .select("role")
                .eq("id", user_id)
                .single()
                .execute()
            )
            role = (profile_res.data or {}).get("role")
        except Exception as e:
            logger.warning(f"Could not fetch profile role for user {user_id}: {e}")

        is_admin = (role == "administrator")
        if not is_admin:
            return {
                "access_token": response.session.access_token,
                "token_type": "bearer",
                "role": role,
                "is_admin": False,
                "has_mfa_linked": False,
                "is_verified": True,
            }

        # Administrator account: check if TOTP factor is linked
        has_mfa_linked = False
        factor_id = None
        try:
            factors = get_user_factors(user_id)
            for f in factors:
                f_type = f.get("factor_type") if isinstance(f, dict) else getattr(f, "factor_type", None)
                f_status = f.get("status") if isinstance(f, dict) else getattr(f, "status", None)
                f_id = f.get("id") if isinstance(f, dict) else getattr(f, "id", None)
                if f_type == "totp" and f_status == "verified":
                    has_mfa_linked = True
                    factor_id = f_id
                    break
        except Exception as e:
            logger.error(f"Error checking MFA factors for admin {user_id}: {e}")

        result = {
            "access_token": response.session.access_token,
            "token_type": "bearer",
            "role": "administrator",
            "is_admin": True,
            "has_mfa_linked": has_mfa_linked,
            "is_verified": False,
        }
        if factor_id:
            result["factor_id"] = factor_id

        return result

    except AuthApiError as e:
        error = str(e).lower()

        if "invalid login credentials" in error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Login failed. Please check your credentials."
            )
        if "email not confirmed" in error:
            logger.warning("login_user: email not confirmed for email=%s", email)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Login failed. Please check your credentials."
            )
        if "too many requests" in error:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many login attempts. Please wait a moment and try again."
            )

        # Fallback for any other auth error
        logger.error(f"login_user AuthApiError: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Login failed. Please check your credentials."
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

        logger.error(f"request_password_reset AuthApiError: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to process password reset request. Please try again."
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
        logger.error(f"verify_reset_token AuthApiError: {e}")

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
        logger.error(f"verify_reset_token unexpected error ({type(e).__name__}): {e}")
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
        logger.error(f"reset_password AuthApiError: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired reset link."
        )
    except Exception as e:
        logger.error(f"reset_password unexpected error ({type(e).__name__}): {e}")
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
        logger.error(f"change_password AuthApiError: {e}")
        raise HTTPException(status_code=400, detail="Password update failed. Please try again.")

def get_user_factors(user_id: str) -> list:
    """Retrieve all MFA factors for a user using the Supabase admin REST API."""
    import httpx
    try:
        url = f"{settings.SUPABASE_URL}/auth/v1/admin/users/{user_id}/factors"
        headers = {
            "apikey": settings.SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
        }
        resp = httpx.get(url, headers=headers, timeout=10.0)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "factors" in data:
                return data["factors"]
            return []
        logger.error(f"Failed to list MFA factors for user {user_id}: {resp.status_code} {resp.text}")
        return []
    except Exception as e:
        logger.error(f"Failed to list MFA factors for user {user_id}: {e}")
        return []


def get_mfa_status(user_id: str, access_token: str) -> dict:
    """Return whether the account is an administrator, has linked MFA, and if current sign-in is verified."""
    import base64
    import json

    # 1. Fetch user role
    role = None
    try:
        profile_res = (
            supabase.table("profiles")
            .select("role")
            .eq("id", user_id)
            .single()
            .execute()
        )
        role = (profile_res.data or {}).get("role")
    except Exception as e:
        logger.error(f"Failed to fetch profile role for user {user_id}: {e}")

    is_admin = (role == "administrator")
    if not is_admin:
        return {
            "role": role,
            "is_admin": False,
            "has_mfa_linked": False,
            "is_verified": True,
            "factor_id": None,
        }

    # 2. Check token AAL level for current sign-in verification
    is_verified = False
    try:
        parts = access_token.split(".")
        if len(parts) == 3:
            padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
            claims = json.loads(base64.urlsafe_b64decode(padded))
            is_verified = (claims.get("aal") == "aal2")
    except Exception as e:
        logger.warning(f"Could not parse token claims for AAL check: {e}")

    # 3. Check enrolled factors
    has_mfa_linked = False
    factor_id = None
    try:
        factors = get_user_factors(user_id)
        for f in factors:
            f_type = f.get("factor_type") if isinstance(f, dict) else getattr(f, "factor_type", None)
            f_status = f.get("status") if isinstance(f, dict) else getattr(f, "status", None)
            f_id = f.get("id") if isinstance(f, dict) else getattr(f, "id", None)
            if f_type == "totp" and f_status == "verified":
                has_mfa_linked = True
                factor_id = f_id
                break
    except Exception as e:
        logger.error(f"Error checking MFA factors for admin {user_id}: {e}")

    return {
        "role": "administrator",
        "is_admin": True,
        "has_mfa_linked": has_mfa_linked,
        "is_verified": is_verified,
        "factor_id": factor_id,
    }


def enroll_mfa(user_id: str, email: str, access_token: str) -> dict:
    """Enroll a TOTP factor for an administrator account. Only administrator accounts can enroll."""
    # 1. Enforce admin check
    profile_res = (
        supabase.table("profiles")
        .select("role")
        .eq("id", user_id)
        .single()
        .execute()
    )
    role = (profile_res.data or {}).get("role")
    if role != "administrator":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrator accounts can link an authenticator app."
        )

    import httpx
    url = f"{settings.SUPABASE_URL}/auth/v1/factors"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "apikey": settings.SUPABASE_ANON_KEY,
        "Content-Type": "application/json",
    }
    body = {
        "factor_type": "totp",
        "issuer": "EventGit",
        "friendly_name": email,
    }

    try:
        resp = httpx.post(url, headers=headers, json=body, timeout=10.0)
        if resp.status_code not in (200, 201):
            logger.error(f"Supabase MFA enroll returned {resp.status_code}: {resp.text}")
            detail = "Failed to enroll authenticator app. Please try again."
            try:
                err_json = resp.json()
                if "msg" in err_json or "message" in err_json:
                    detail = err_json.get("msg") or err_json.get("message")
            except Exception:
                pass
            raise HTTPException(
                status_code=resp.status_code if resp.status_code < 500 else 400,
                detail=detail
            )

        data = resp.json()
        qr_code = data.get("totp", {}).get("qr_code", "")
        if qr_code and not qr_code.startswith("data:image"):
            qr_code = f"data:image/svg+xml;utf-8,{qr_code}"
            data["totp"]["qr_code"] = qr_code

        return {
            "factor_id": data.get("id"),
            "totp": data.get("totp", {}),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in enroll_mfa: {e}")
        raise HTTPException(status_code=500, detail="Failed to initiate authenticator linking.")


def verify_mfa(user_id: str, access_token: str, code: str, factor_id: str | None = None) -> dict:
    """
    Check the code the administrator enters from the app.
    When correct, verifies the factor/challenge, marks current sign-in as verified (elevating to AAL2),
    and returns the new session access token. Refuses a wrong code with a reason.
    Only administrator accounts can have codes checked.
    """
    # 1. Enforce admin check
    profile_res = (
        supabase.table("profiles")
        .select("role")
        .eq("id", user_id)
        .single()
        .execute()
    )
    role = (profile_res.data or {}).get("role")
    if role != "administrator":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrator accounts can verify authentication codes."
        )

    import httpx

    # 2. If factor_id is not provided, look up the user's active/latest factor
    target_factor_id = factor_id
    if not target_factor_id:
        try:
            factors = get_user_factors(user_id)
            for f in factors:
                f_type = f.get("factor_type") if isinstance(f, dict) else getattr(f, "factor_type", None)
                f_id = f.get("id") if isinstance(f, dict) else getattr(f, "id", None)
                if f_type == "totp":
                    target_factor_id = f_id
                    break
        except Exception as e:
            logger.error(f"Failed to find factor for user {user_id}: {e}")

    if not target_factor_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No authenticator factor found for account. Please link an authenticator app first."
        )

    headers = {
        "Authorization": f"Bearer {access_token}",
        "apikey": settings.SUPABASE_ANON_KEY,
        "Content-Type": "application/json",
    }

    # 3. Create a challenge
    challenge_url = f"{settings.SUPABASE_URL}/auth/v1/factors/{target_factor_id}/challenge"
    try:
        challenge_resp = httpx.post(challenge_url, headers=headers, json={}, timeout=10.0)
        if challenge_resp.status_code not in (200, 201):
            logger.error(f"Supabase MFA challenge returned {challenge_resp.status_code}: {challenge_resp.text}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to create verification challenge. Please try again."
            )
        challenge_id = challenge_resp.json().get("id")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error creating MFA challenge: {e}")
        raise HTTPException(status_code=500, detail="Failed to create verification challenge.")

    # 4. Verify code against the challenge
    verify_url = f"{settings.SUPABASE_URL}/auth/v1/factors/{target_factor_id}/verify"
    verify_body = {
        "challenge_id": challenge_id,
        "code": code.strip(),
    }
    try:
        verify_resp = httpx.post(verify_url, headers=headers, json=verify_body, timeout=10.0)
        if verify_resp.status_code not in (200, 201):
            logger.warning(f"Supabase MFA verify failed with status {verify_resp.status_code}: {verify_resp.text}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid verification code. Please check your authenticator app and try again."
            )

        data = verify_resp.json()
        new_access_token = data.get("access_token")
        if not new_access_token:
            raise HTTPException(status_code=500, detail="MFA verification succeeded but no access token returned.")

        return {
            "access_token": new_access_token,
            "token_type": "bearer",
            "is_verified": True,
            "message": "Sign-in successfully verified.",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in verify_mfa: {e}")
        raise HTTPException(status_code=500, detail="Verification failed due to a server error.")
