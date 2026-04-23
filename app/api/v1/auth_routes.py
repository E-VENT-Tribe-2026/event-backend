import os
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from supabase import create_client, Client

from app.schemas.auth_schema import RegisterRequest, LoginRequest
# Removed 'reset_password' from the import below to prevent function name collisions
from app.services.auth_service import register_user, login_user, request_password_reset
from app.core.dependencies import get_current_user
import httpx

class PasswordResetRequestBody(BaseModel):
    email: EmailStr

class ResetPasswordPayload(BaseModel):
    access_token: str
    new_password: str

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
async def update_user_password(payload: ResetPasswordPayload):
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise HTTPException(status_code=500, detail="Missing Supabase Env Vars")

    try:
        # Step 1: Verify the user token using the standard client
        user_response = supabase.auth.get_user(payload.access_token)
        if not user_response.user:
            raise HTTPException(status_code=401, detail="Invalid token")

        # Step 2: Direct REST API Call (Bypasses the python library entirely)
        # This forces Supabase to recognize the Admin privileges.
        url = f"{SUPABASE_URL}/auth/v1/admin/users/{user_response.user.id}"
        
        headers = {
            "apikey": SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}", # MUST be the Service Key here
            "Content-Type": "application/json"
        }
        
        data = {
            "password": payload.new_password
        }

        # Make the request to force the password change
        async with httpx.AsyncClient() as client:
            response = await client.put(url, headers=headers, json=data)

        # Catch specific errors from the REST API
        if response.status_code != 200:
            error_msg = response.json().get("msg", response.text)
            raise HTTPException(status_code=400, detail=f"Admin Update Failed: {error_msg}")

        return {"message": "Password updated successfully."}

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Auth Error: {str(e)}")