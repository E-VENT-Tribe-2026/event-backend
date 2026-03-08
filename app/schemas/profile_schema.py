from pydantic import BaseModel
from typing import Optional


class ProfileResponse(BaseModel):
    id: str
    full_name: Optional[str]
    phone: Optional[str]
    avatar_url: Optional[str]
    bio: Optional[str]
    visibility: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]


class ProfileUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    visibility: Optional[str] = None


class LocationUpdateRequest(BaseModel):
    latitude: float
    longitude: float