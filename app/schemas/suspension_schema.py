from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator

SUSPENSION_REASON_MAX_LENGTH = 1000


class SuspensionReasonRequest(BaseModel):
    reason: str = Field(..., description="Why the account is suspended, or why the suspension is lifted. Required.")

    @field_validator("reason")
    @classmethod
    def reason_not_blank(cls, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise ValueError("A reason is required.")
        if len(value) > SUSPENSION_REASON_MAX_LENGTH:
            raise ValueError(f"The reason can have at most {SUSPENSION_REASON_MAX_LENGTH} characters.")
        return value


class SuspensionResponse(BaseModel):
    user_id: str
    status: Literal["active", "suspended"]
    suspended_since: Optional[str] = None
    cancelled_events_count: int = 0
    joined_events_removed_count: int = 0