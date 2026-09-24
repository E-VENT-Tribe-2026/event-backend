from pydantic import BaseModel, ConfigDict
from typing import Optional, List


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


class LocationUpdateRequest(BaseModel):
    latitude: float
    longitude: float