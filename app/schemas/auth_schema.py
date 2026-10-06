import re
from datetime import date

from pydantic import BaseModel, EmailStr, field_validator, model_validator
from typing import List, Optional

from app.utils.schema_validators import validate_username_value, validate_full_name_value


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    username: Optional[str] = None
    full_name: Optional[str] = None
    dob: date
    gender: str
    interests: List[str] = []

    @field_validator("username", mode="before")
    @classmethod
    def validate_username(cls, v):
        if v is None:
            return None
        return validate_username_value(v)

    @field_validator("full_name", mode="before")
    @classmethod
    def validate_full_name(cls, v):
        if v is None:
            return None
        return validate_full_name_value(v)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: Optional[str] = None
    is_admin: bool = False
    has_mfa_linked: bool = False
    is_verified: bool = True
    factor_id: Optional[str] = None


class LoginResponse(AuthResponse):
    pass


class MFAStatusResponse(BaseModel):
    role: Optional[str] = None
    is_admin: bool = False
    has_mfa_linked: bool = False
    is_verified: bool = False
    factor_id: Optional[str] = None


class MFATOTPData(BaseModel):
    qr_code: str
    secret: str
    uri: str


class MFAEnrollResponse(BaseModel):
    factor_id: str
    totp: MFATOTPData


class MFAVerifyRequest(BaseModel):
    code: str
    factor_id: Optional[str] = None


class MFAVerifyResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    is_verified: bool = True
    message: str = "Sign-in successfully verified."


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    confirm_new_password: str

    @model_validator(mode="after")
    def passwords_match(self):
        if self.new_password != self.confirm_new_password:
            raise ValueError("New password and confirm password do not match.")
        return self


class ChooseUsernameRequest(BaseModel):
    username: str
    full_name: str

    @field_validator("username", mode="before")
    @classmethod
    def validate_username(cls, v):
        return validate_username_value(v)

    @field_validator("full_name", mode="before")
    @classmethod
    def validate_full_name(cls, v):
        return validate_full_name_value(v)
