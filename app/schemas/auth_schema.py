import re
from datetime import date

from pydantic import BaseModel, EmailStr, field_validator, model_validator
from typing import List, Optional

_ALLOWED_NAME_PUNCTUATION = set(".'-,\"''\u2019()")


def _validate_username_value(v: str) -> str:
    """Shared username validation logic for Pydantic field validators."""
    normalized = str(v).lower()
    if not re.fullmatch(r"[a-z0-9._]{3,20}", normalized):
        raise ValueError(
            "Username must be between 3 and 20 characters and contain only lowercase "
            "letters, digits, underscores, and full stops."
        )
    return normalized


def _validate_full_name_value(v: str) -> str:
    """Shared full-name validation logic for Pydantic field validators.

    Leading/trailing whitespace (including newlines) is stripped before validation,
    consistent with how name fields are handled elsewhere. This intentionally differs
    from the username validator, which rejects trailing newlines outright.
    """
    stripped = str(v).strip()
    if not stripped:
        raise ValueError("Full name is required and cannot be empty or only spaces.")
    if not (3 <= len(stripped) <= 50):
        raise ValueError(
            "Full name must be between 3 and 50 characters once leading and trailing "
            "spaces are removed."
        )
    if not any(c.isalpha() for c in stripped):
        raise ValueError("Full name must contain at least one letter.")
    for c in stripped:
        if not (c.isalpha() or c == " " or c in _ALLOWED_NAME_PUNCTUATION):
            raise ValueError(
                "Full name must contain only letters, spaces, and common punctuation."
            )
    return stripped


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
        return _validate_username_value(v)

    @field_validator("full_name", mode="before")
    @classmethod
    def validate_full_name(cls, v):
        if v is None:
            return None
        return _validate_full_name_value(v)


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
        return _validate_username_value(v)

    @field_validator("full_name", mode="before")
    @classmethod
    def validate_full_name(cls, v):
        return _validate_full_name_value(v)
