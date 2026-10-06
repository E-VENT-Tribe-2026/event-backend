from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.event_search_schema import SearchEventsError


_EVENT_ID = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


class EventDetailsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    event_id: str = Field(min_length=1, max_length=36, pattern=_EVENT_ID)

    @field_validator("event_id")
    @classmethod
    def strip_event_id(cls, value: str) -> str:
        return value.strip()


class EventDetails(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    category: Optional[str] = None
    cost: Optional[float] = None
    max_capacity: Optional[int] = None
    start_datetime: Optional[str] = None
    end_datetime: Optional[str] = None
    location_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    created_by: Optional[str] = None
    status: str


class EventDetailsResponse(BaseModel):
    request_id: str = Field(min_length=1)
    success: bool
    event: Optional[EventDetails] = None
    error: Optional[SearchEventsError] = None
