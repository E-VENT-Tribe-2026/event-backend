import os
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from supabase import create_client, Client

from app.schemas.auth_schema import RegisterRequest, LoginRequest, ChangePasswordRequest
from app.services.auth_service import register_user, login_user, request_password_reset, change_password, reset_password
from app.core.dependencies import get_current_user
import httpx

class PasswordResetRequestBody(BaseModel):
    email: EmailStr

class ResetPasswordPayload(BaseModel):
    access_token: str
    current_password: str
    new_password: str
    confirm_password: str

router = APIRouter()

# 1. Fetch Environment Variables
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

# 2. Safe Client Initialization (Prevents Uvicorn crashing if Render is missing keys)
if not all([SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPABASE_ANON_KEY]):
    print("CRITICAL WARNING: Missing Supabase Environment Variables!")
    supabase_admin = None
    supabase = None
else:
    # Admin Client - WARNING: This client has full database bypass privileges.
    supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    # Standard Client - just for verifying the token securely
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


@router.post("/register")
def register(data: RegisterRequest):
    return register_user(
        email=data.email,
        password=data.password, 
        full_name=data.full_name,
        dob=data.dob.isoformat(), 
        gender=data.gender,
        interests=data.interests
    )

@router.post("/login")
def login(data: LoginRequest):
    return login_user(
        email=data.email,
        password=data.password
    )

@router.get("/me")
def get_profile(user = Depends(get_current_user)):
    return {
        "id": user.id,
        "email": user.email,
    }

@router.post("/forgot-password")
def forgot_password(body: PasswordResetRequestBody):
    return request_password_reset(body.email)


@router.post("/reset-password")
def update_user_password(payload: ResetPasswordPayload):
    if payload.new_password != payload.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match.")

    # Decode the JWT directly to extract user info — no Supabase call needed
    from jose import jwt, JWTError
    from app.core.config import settings

    try:
        claims = jwt.decode(
            payload.access_token,
            settings.SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
        user_id = claims.get("sub")
        email = claims.get("email")
        if not user_id or not email:
            raise HTTPException(status_code=401, detail="Invalid token.")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    return change_password(
        email=email,
        user_id=user_id,
        current_password=payload.current_password,
        new_password=payload.new_password
    )


@router.post("/change-password")
def change_user_password(data: ChangePasswordRequest, user=Depends(get_current_user)):
    return change_password(
        email=user.email,
        user_id=user.id,
        current_password=data.current_password,
        new_password=data.new_password
    )