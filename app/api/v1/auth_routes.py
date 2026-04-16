from fastapi import APIRouter, Depends
from app.schemas.auth_schema import RegisterRequest, LoginRequest
from app.services.auth_service import register_user, login_user, request_password_reset, reset_password
from app.core.dependencies import get_current_user
from pydantic import BaseModel, EmailStr

class PasswordResetRequestBody(BaseModel):
    email: EmailStr

class PasswordResetBody(BaseModel):
    access_token: str
    new_password: str

router = APIRouter()


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
def reset_password_route(body: PasswordResetBody):
    return reset_password(body.access_token, body.new_password)