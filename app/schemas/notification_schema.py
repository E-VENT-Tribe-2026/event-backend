from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from app.schemas.profile_schema import UserSummary


class NotificationResponse(BaseModel):
    id: int
    user_id: str
    event_id: Optional[str]
    type: str
    message: str
    is_read: bool
    created_at: datetime
    related_user_id: Optional[str] = None
    related_user: Optional[UserSummary] = None


class NotificationUpdateRequest(BaseModel):
    is_read: bool = True


class BulkDeleteRequest(BaseModel):
    notification_ids: List[int]