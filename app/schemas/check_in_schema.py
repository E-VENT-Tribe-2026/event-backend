from typing import Optional

from pydantic import BaseModel, field_validator, model_validator

from app.schemas.profile_schema import UserSummary


class CheckInRequest(BaseModel):
    code: Optional[str] = None
    qr_content: Optional[str] = None

    @field_validator("code", "qr_content", mode="before")
    @classmethod
    def strip_code(cls, value):
        if value is None:
            return None
        return str(value).strip() or None

    @model_validator(mode="after")
    def require_code(self):
        if not self.code and not self.qr_content:
            raise ValueError("A check-in code is required.")
        return self


class CheckInResponse(BaseModel):
    checked_in: bool = True
    already_checked_in: bool = False
    checked_in_at: Optional[str] = None


class CheckInCodeResponse(BaseModel):
    event_id: str
    code: str
    qr_content: str


class CheckInListItem(BaseModel):
    user: UserSummary
    checked_in_at: Optional[str] = None


class CheckInListResponse(BaseModel):
    event_id: str
    checked_in_count: int
    participant_count: int
    viewer_checked_in: bool
    include_times: bool
    items: list[CheckInListItem]
