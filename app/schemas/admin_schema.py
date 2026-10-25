from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict
from app.schemas.warning_schema import PersonSummary


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
    # #191: null for an administrator's entry, which shows the role only.
    warning_count: Optional[int] = None
    status: Optional[Literal["active", "suspended"]] = None
    model_config = ConfigDict(extra="ignore")

class AdminUserListCounters(BaseModel):
    administrators: int
    suspended: int
    with_warnings: int

class AdminUserListResponse(BaseModel):
    items: List[AdminUserListItem]
    total: int
    page: int
    limit: int
    total_pages: int


class AdminEventOrganizerSummary(BaseModel):
    id: Optional[str] = None
    username: Optional[str] = None
    full_name: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    avatar_kind: Optional[str] = "icon"
    icon_id: Optional[str] = None

    model_config = ConfigDict(extra="ignore")


class AdminEventListItem(BaseModel):
    id: str
    title: str = ""
    date: Optional[str] = None
    start_datetime: Optional[str] = None
    end_datetime: Optional[str] = None
    status: Optional[str] = None
    is_cancelled: bool = False
    organizer: Optional[AdminEventOrganizerSummary] = None
    banner: Optional[str] = None
    banner_url: Optional[str] = None

    model_config = ConfigDict(extra="ignore")


class AdminEventListResponse(BaseModel):
    items: List[AdminEventListItem]
    total: int
    page: int
    limit: int
    total_pages: int


class AdminUserEventItem(BaseModel):
    id: str
    title: str = ""
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


class AdminAccountResponse(BaseModel):
    id: str
    email: Optional[str] = None
    username: Optional[str] = None
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    avatar_kind: Optional[str] = "icon"
    icon_id: Optional[str] = None
    admin_since: Optional[str] = None
    role: str = "administrator"

    model_config = ConfigDict(extra="ignore")


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
    admin_since: Optional[str] = None
    role: Optional[str] = None
    warnings: List[str] = []
    warning_history: List[str] = []
    organized_events: AdminUserEventCategories
    joined_events: AdminUserEventCategories
        # #191: null for an administrator account.
    profile_visibility: Optional[str] = None
    status: Optional[Literal["active", "suspended"]] = None
    suspended_since: Optional[str] = None
    suspension_reason: Optional[str] = None
    warning_count: Optional[int] = None
    friends: List[PersonSummary] = []
    blocked_users: List[PersonSummary] = []
    blocked_by: List[PersonSummary] = []

    model_config = ConfigDict(extra="ignore")


class AdminParticipantItem(BaseModel):
    id: Optional[str] = None
    username: Optional[str] = None
    full_name: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    avatar_kind: Optional[str] = "icon"
    icon_id: Optional[str] = None
    status: Optional[str] = "registered"
    registered_at: Optional[str] = None
    is_admin: bool = False

    model_config = ConfigDict(extra="ignore")


class AdminChatMessageSender(BaseModel):
    id: Optional[str] = None
    username: Optional[str] = None
    full_name: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    avatar_kind: Optional[str] = "icon"
    icon_id: Optional[str] = None

    model_config = ConfigDict(extra="ignore")


class AdminChatMessageItem(BaseModel):
    id: int | str
    sender_id: Optional[str] = None
    sender: Optional[AdminChatMessageSender] = None
    username: Optional[str] = None
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    avatar_kind: Optional[str] = "icon"
    icon_id: Optional[str] = None
    text: str
    content: str
    time: Optional[str] = None
    created_at: Optional[str] = None
    is_system_message: bool = False
    type: Optional[str] = "chat"

    model_config = ConfigDict(extra="ignore")


class AdminEventDetailResponse(BaseModel):
    id: str
    title: str = ""
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
    cancellation_reason: Optional[str] = None
    organizer: Optional[AdminEventOrganizerSummary] = None
    participant_count: int = 0
    participants: List[AdminParticipantItem] = []
    chats: List[AdminChatMessageItem] = []
    chat: List[AdminChatMessageItem] = []
    banner: Optional[str] = None
    banner_url: Optional[str] = None

    model_config = ConfigDict(extra="ignore")


class GrantAdminRoleResponse(BaseModel):
    message: str = "User made administrator successfully."
    user_id: str
    role: str = "administrator"
    admin_since: Optional[str] = None
    summary: Optional[dict] = None

    model_config = ConfigDict(extra="ignore")
