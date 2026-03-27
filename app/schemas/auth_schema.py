from datetime import date

from pydantic import BaseModel, EmailStr
from typing import List, Optional


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: Optional[str] = None
    dob: date           
    gender: str         
    interests: List[str] = []


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"