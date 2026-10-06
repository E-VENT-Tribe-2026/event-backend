from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.event_search_schema import SearchEventsError


class DraftNewEventInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=5000)
    category: Optional[str] = Field(default=None, max_length=100)
    cost: Optional[float] = Field(default=None, ge=0)
    max_capacity: Optional[int] = Field(default=None, ge=1)
    start_datetime: str
    end_datetime: str
    location_name: Optional[str] = Field(default=None, max_length=300)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)

    @field_validator("start_datetime", "end_datetime")
    @classmethod
    def validate_iso_datetime(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("Datetime string is required.")
        try:
            # Preserves timezone information while validating ISO format
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("Must be a valid ISO 8601 datetime.")
        return v.strip()


class DraftEventPreview(BaseModel):
    title: str
    description: Optional[str] = None
    category: Optional[str] = None
    cost: Optional[float] = None
    max_capacity: Optional[int] = None
    start_datetime: str
    end_datetime: str
    location_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class ValidationIssue(BaseModel):
    code: str
    field: Optional[str] = None
    message: str
    severity: Literal["error", "warning"] = "error"


class DraftNewEventResponse(BaseModel):
    request_id: str = Field(min_length=1)
    success: bool
    draft: Optional[DraftEventPreview] = None
    validation_issues: list[ValidationIssue] = []
    error: Optional[SearchEventsError] = None
