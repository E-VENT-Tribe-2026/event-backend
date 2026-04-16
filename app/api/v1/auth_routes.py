from fastapi import APIRouter,HTTPException, Depends
from app.schemas.auth_schema import RegisterRequest, LoginRequest
from app.services.auth_service import register_user, login_user, request_password_reset, reset_password
from app.core.dependencies import get_current_user
from pydantic import BaseModel, EmailStr
from supabase import create_client, Client
import os

class PasswordResetRequestBody(BaseModel):
    email: EmailStr

class ResetPasswordPayload(BaseModel):
    access_token: str
    new_password: str

router = APIRouter()

# 1. Initialize the Admin Client (Requires your SERVICE_ROLE_KEY from the dashboard)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

# WARNING: This client has full database bypass privileges. Keep the key secret.
supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# 2. Also keep a standard client just for verifying the token securely
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
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

@router.post("/api/auth/reset-password")
def reset_password(payload: ResetPasswordPayload):
    try:
        # Step 1: Verify the token is real and get the user's ID
        user_response = supabase.auth.get_user(payload.access_token)
        if not user_response.user:
            raise HTTPException(status_code=401, detail="Invalid token")

        # Step 2: Use the ADMIN client to force the password update
        supabase_admin.auth.admin.update_user_by_id(
            user_response.user.id,
            {"password": payload.new_password}
        )
        
        return {"message": "Password updated successfully."}

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Auth Error: {str(e)}")