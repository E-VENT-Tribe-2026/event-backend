from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

WARNING_REASON_MAX_LENGTH = 1000


class PersonSummary(BaseModel):
    """Profile picture, full name and username of a person shown in the panel."""
    id: Optional[str] = None
    username: Optional[str] = None
    full_name: Optional[str] = None
    display_name: Optional[str] = None
    avatar_kind: Optional[str] = "icon"
    icon_id: Optional[str] = None
    avatar_url: Optional[str] = None

    model_config = ConfigDict(extra="ignore")


class GiveWarningRequest(BaseModel):
    reason: str = Field(..., description="Why the user is warned. Required, 1 to 1000 characters.")
    about_type: Optional[Literal["event", "chat_message", "profile"]] = Field(
        None, description="What the warning is about, if it is about one item.")
    about_id: Optional[str] = Field(None, description="Identifier of that item.")

    @field_validator("reason")
    @classmethod
    def reason_not_blank(cls, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise ValueError("A reason is required.")
        if len(value) > WARNING_REASON_MAX_LENGTH:
            raise ValueError(f"The reason can have at most {WARNING_REASON_MAX_LENGTH} characters.")
        return value

    @model_validator(mode="after")
    def about_both_or_neither(self):
        if (self.about_type is None) != (self.about_id is None):
            raise ValueError("Send about_type and about_id together, or neither.")
        return self


class WarningAbout(BaseModel):
    type: str
    id: str


class WarningHistoryItem(BaseModel):
    id: int
    created_at: str
    reason: str
    about: Optional[WarningAbout] = None
    given_by: Optional[PersonSummary] = None
    is_withdrawn: bool = False
    withdrawn_at: Optional[str] = None
    withdrawn_by: Optional[PersonSummary] = None
    acknowledged_at: Optional[str] = None


class WarningHistoryResponse(BaseModel):
    user_id: str
    items: List[WarningHistoryItem]


class PendingWarningItem(BaseModel):
    id: int
    created_at: str
    reason: str
    about: Optional[WarningAbout] = None


class PendingWarningsResponse(BaseModel):
    items: List[PendingWarningItem]


class AcknowledgeWarningResponse(BaseModel):
    id: int
    acknowledged_at: str


class AuditLogTarget(BaseModel):
    type: Optional[str] = None
    id: Optional[str] = None
    user: Optional[PersonSummary] = None


class AuditLogItem(BaseModel):
    id: Optional[str] = None
    created_at: Optional[str] = None
    action: str
    administrator: Optional[PersonSummary] = None
    target: AuditLogTarget
    description: Optional[str] = None
    details: List[str] = []


class AuditLogResponse(BaseModel):
    items: List[AuditLogItem]
    has_more: bool
    next_before: Optional[str] = Field(
        None, description="Send this as `before` to load the next page. Null when there is nothing more.")