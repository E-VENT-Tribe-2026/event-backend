import os
import logging
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, EmailStr
from supabase import create_client, Client

from app.schemas.auth_schema import (
    RegisterRequest,
    LoginRequest,
    ChangePasswordRequest,
    ChooseUsernameRequest,
    MFAVerifyRequest,
    MFAVerifyResponse,
    MFAEnrollResponse,
    MFAStatusResponse,
)
from app.services.auth_service import (
    register_user,
    login_user,
    request_password_reset,
    verify_reset_token,
    change_password,
    enroll_mfa,
    verify_mfa,
    get_mfa_status,
)
from app.services.auth_service import reset_password as reset_user_password
from app.core.dependencies import get_current_user, security
from app.core.limiter import limiter
import httpx

logger = logging.getLogger(__name__)


class PasswordResetRequestBody(BaseModel):
    email: EmailStr

class VerifyResetTokenPayload(BaseModel):
    token_hash: str

class ResetPasswordPayload(BaseModel):
    access_token: str
    new_password: str

router = APIRouter()

# 1. Fetch Environment Variables
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

# 2. Safe Client Initialization
if not all([SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPABASE_ANON_KEY]):
    logger.critical("Missing Supabase environment variables — email auth will not work.")
    supabase_admin = None
    supabase = None
else:
    supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


@router.post("/register")
@limiter.limit("10/minute")
def register(request: Request, data: RegisterRequest):
    return register_user(
        email=data.email,
        password=data.password,
        full_name=data.full_name,
        dob=data.dob.isoformat(),
        gender=data.gender,
        interests=data.interests,
        username=data.username
    )


@router.post("/login")
@limiter.limit("10/minute")
def login(request: Request, data: LoginRequest):
    return login_user(
        email=data.email,
        password=data.password
    )


@router.get("/me")
@limiter.limit("60/minute")
def get_profile(request: Request, user=Depends(get_current_user)):
    username = None
    role = None
    if supabase:
        try:
            profile = supabase.table("profiles").select("username, role").eq("id", user.id).single().execute()
            if profile.data:
                username = profile.data.get("username")
                role = profile.data.get("role")
        except Exception:
            pass
    return {
        "id": user.id,
        "email": user.email,
        "username": username,
        "role": role,
    }


@router.get("/mfa/status")
@limiter.limit("60/minute")
def mfa_status(
    request: Request,
    credentials=Depends(security),
    user=Depends(get_current_user)
):
    """
    Check if the account holds the administrator role, whether an authenticator app
    has been linked, and whether the current sign-in has been verified.
    Works for both email/password sign-in and Google sign-in.
    """
    return get_mfa_status(
        user_id=user.id,
        access_token=credentials.credentials
    )


@router.post("/mfa/enroll")
@limiter.limit("10/minute")
def mfa_enroll(
    request: Request,
    credentials=Depends(security),
    user=Depends(get_current_user)
):
    """
    Let an administrator account link an authenticator app to their account
    the first time they sign in as an administrator.
    Returns factor details and QR code SVG to scan.
    Only administrator accounts can link an app.
    """
    return enroll_mfa(
        user_id=user.id,
        email=user.email or "",
        access_token=credentials.credentials
    )


@router.post("/mfa/verify")
@limiter.limit("15/minute")
def mfa_verify(
    request: Request,
    payload: MFAVerifyRequest,
    credentials=Depends(security),
    user=Depends(get_current_user)
):
    """
    Check the code the administrator enters from the authenticator app.
    When correct, marks the current sign-in as verified (AAL2) and returns
    the upgraded access token. Refuses wrong codes with a clear reason.
    Only administrator accounts can have codes checked.
    """
    return verify_mfa(
        user_id=user.id,
        access_token=credentials.credentials,
        code=payload.code,
        factor_id=payload.factor_id
    )


@router.post("/choose-username")
def choose_username_endpoint(data: ChooseUsernameRequest, user=Depends(get_current_user)):
    from app.services.profile_service import choose_username
    return choose_username(user_id=user.id, username=data.username, full_name=data.full_name)


@router.post("/forgot-password")
@limiter.limit("5/minute")
def forgot_password(request: Request, body: PasswordResetRequestBody):
    return request_password_reset(body.email)


@router.post("/verify-reset-token")
@limiter.limit("5/minute")
def verify_token(request: Request, payload: VerifyResetTokenPayload):
    return verify_reset_token(token_hash=payload.token_hash)


@router.post("/reset-password")
@limiter.limit("5/minute")
def update_user_password(request: Request, payload: ResetPasswordPayload):
    return reset_user_password(
        access_token=payload.access_token,
        new_password=payload.new_password
    )


@router.post("/change-password")
@limiter.limit("5/minute")
def change_user_password(request: Request, data: ChangePasswordRequest, user=Depends(get_current_user)):
    return change_password(
        email=user.email,
        user_id=user.id,
        current_password=data.current_password,
        new_password=data.new_password
    )
