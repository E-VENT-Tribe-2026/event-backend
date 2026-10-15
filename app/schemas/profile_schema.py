from pydantic import BaseModel, ConfigDict, field_validator
from typing import Optional, List

from app.core.input_limits import BIO_MAX_LENGTH
from app.utils.schema_validators import (
    validate_username_value,
    validate_full_name_value,
    validate_text_value,
)


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
        return validate_username_value(v)

    @field_validator("full_name", mode="before")
    @classmethod
    def validate_full_name(cls, v):
        if v is None:
            return None
        return validate_full_name_value(v)

    @field_validator("bio", mode="before")
    @classmethod
    def validate_bio(cls, v):
        # None means "not changed"; an empty string clears the biography.
        if v is None:
            return None
        return validate_text_value(
            v, field_label="Biography", min_length=0, max_length=BIO_MAX_LENGTH
        )


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