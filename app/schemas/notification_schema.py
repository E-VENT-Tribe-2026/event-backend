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
        # Warnings (#191). For other notifications is_warning is False and the rest null.
    # For a warning, `message` is the reason.
    warning_id: Optional[int] = None
    is_warning: bool = False
    warning_acknowledged: Optional[bool] = None
    warning_withdrawn: Optional[bool] = None


class NotificationUpdateRequest(BaseModel):
    is_read: bool = True


class BulkDeleteRequest(BaseModel):
    notification_ids: List[int]