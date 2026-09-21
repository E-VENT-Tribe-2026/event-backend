import os
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, EmailStr
from supabase import create_client, Client

from app.schemas.auth_schema import RegisterRequest, LoginRequest, ChangePasswordRequest
from app.services.auth_service import register_user, login_user, request_password_reset, verify_reset_token, change_password
from app.services.auth_service import reset_password as reset_user_password
from app.core.dependencies import get_current_user
from app.core.limiter import limiter
import httpx

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

import logging
logger = logging.getLogger(__name__)

# 2. Safe Client Initialization (Prevents Uvicorn crashing if Render is missing keys)
if not all([SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPABASE_ANON_KEY]):
    logger.critical("Missing Supabase environment variables — email auth will not work.")
    supabase_admin = None
    supabase = None
else:
    # Admin Client - WARNING: This client has full database bypass privileges.
    supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    # Standard Client - just for verifying the token securely
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
        interests=data.interests
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
    return {
        "id": user.id,
        "email": user.email,
    }

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