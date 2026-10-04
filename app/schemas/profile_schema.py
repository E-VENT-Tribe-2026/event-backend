import re
from pydantic import BaseModel, ConfigDict, field_validator
from typing import Optional, List

_ALLOWED_NAME_PUNCTUATION = set(".'-,\"''()")


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
    """Shared full-name validation logic for Pydantic field validators."""
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


class ProfileResponse(BaseModel):
    id: str
    username: Optional[str] = None
    full_name: Optional[str] = None
    phone: Optional[str] = None
    avatar_url: Optional[str] = None
    avatar_kind: Optional[str] = "icon"
    icon_id: Optional[str] = None
    banner: Optional[str] = None
    banner_url: Optional[str] = None
    bio: Optional[str] = None
    interests: Optional[List[str]] = None
    visibility: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    role: Optional[str] = None

    model_config = ConfigDict(extra="ignore")


class ProfileUpdateRequest(BaseModel):
    username: Optional[str] = None
    full_name: Optional[str] = None
    phone: Optional[str] = None
    avatar_url: Optional[str] = None
    avatar_kind: Optional[str] = None
    icon_id: Optional[str] = None
    banner: Optional[str] = None
    banner_url: Optional[str] = None
    profile_picture: Optional[str] = None
    bio: Optional[str] = None
    interests: Optional[List[str]] = None
    visibility: Optional[str] = None

    model_config = ConfigDict(extra="ignore")

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


class LocationUpdateRequest(BaseModel):
    latitude: float
    longitude: float


class UserSummary(BaseModel):
    """Minimal, consistent way to show a user next to their content (chat messages, participant lists, etc.).

    This is the canonical UserSummary shape; USER_SUMMARY_COLUMNS and
    build_user_summary (app.services.profile_service) must be kept in sync with it.
    """
    id: str
    username: Optional[str] = None
    full_name: Optional[str] = None
    display_name: Optional[str] = None
    avatar_kind: str = "icon"
    icon_id: Optional[str] = None
    avatar_url: Optional[str] = None