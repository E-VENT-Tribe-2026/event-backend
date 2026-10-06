from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict


class AdminEventCounts(BaseModel):
    total: int
    upcoming: int
    past: int
    cancelled: int


class AdminCountsResponse(BaseModel):
    total_users: int
    events: AdminEventCounts


class AdminUserListItem(BaseModel):
    id: str
    username: Optional[str] = None
    full_name: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    avatar_kind: Optional[str] = "icon"
    icon_id: Optional[str] = None
    role: Optional[str] = None
    is_admin: bool = False
    created_at: Optional[str] = None

    model_config = ConfigDict(extra="ignore")


class AdminUserListResponse(BaseModel):
    items: List[AdminUserListItem]
    total: int
    page: int
    limit: int
    total_pages: int


class AdminEventOrganizerSummary(BaseModel):
    id: str
    username: Optional[str] = None
    full_name: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    avatar_kind: Optional[str] = "icon"
    icon_id: Optional[str] = None

    model_config = ConfigDict(extra="ignore")


class AdminEventListItem(BaseModel):
    id: str
    title: str
    date: Optional[str] = None
    start_datetime: Optional[str] = None
    end_datetime: Optional[str] = None
    status: Optional[str] = None
    is_cancelled: bool = False
    organizer: Optional[AdminEventOrganizerSummary] = None

    model_config = ConfigDict(extra="ignore")


class AdminEventListResponse(BaseModel):
    items: List[AdminEventListItem]
    total: int
    page: int
    limit: int
    total_pages: int


class AdminUserEventItem(BaseModel):
    id: str
    title: str
    date: Optional[str] = None
    start_datetime: Optional[str] = None
    end_datetime: Optional[str] = None
    status: Optional[str] = None
    is_cancelled: bool = False

    model_config = ConfigDict(extra="ignore")


class AdminUserEventCategories(BaseModel):
    upcoming: List[AdminUserEventItem] = []
    past: List[AdminUserEventItem] = []
    cancelled: List[AdminUserEventItem] = []


class AdminUserDetailResponse(BaseModel):
    id: str
    username: Optional[str] = None
    full_name: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    avatar_kind: Optional[str] = "icon"
    icon_id: Optional[str] = None
    created_at: Optional[str] = None
    is_admin: bool = False
    role: Optional[str] = None
    organized_events: AdminUserEventCategories
    joined_events: AdminUserEventCategories

    model_config = ConfigDict(extra="ignore")


class AdminParticipantItem(BaseModel):
    id: str
    username: Optional[str] = None
    full_name: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    avatar_kind: Optional[str] = "icon"
    icon_id: Optional[str] = None
    status: Optional[str] = "registered"
    registered_at: Optional[str] = None

    model_config = ConfigDict(extra="ignore")


class AdminEventDetailResponse(BaseModel):
    id: str
    title: str
    category: Optional[str] = None
    description: Optional[str] = None
    date: Optional[str] = None
    start_datetime: Optional[str] = None
    end_datetime: Optional[str] = None
    location_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    cost: Optional[float] = 0
    max_capacity: Optional[int] = None
    status: Optional[str] = None
    is_cancelled: bool = False
    organizer: Optional[AdminEventOrganizerSummary] = None
    participant_count: int = 0
    participants: List[AdminParticipantItem] = []

    model_config = ConfigDict(extra="ignore")


class GrantAdminRoleResponse(BaseModel):
    message: str = "Administrator role granted successfully."
    user_id: str
    role: str = "administrator"
