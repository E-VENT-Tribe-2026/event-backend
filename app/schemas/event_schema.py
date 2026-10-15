from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime
from uuid import UUID

from app.core.input_limits import (
    EVENT_TITLE_MIN_LENGTH,
    EVENT_TITLE_MAX_LENGTH,
    EVENT_DESCRIPTION_MAX_LENGTH,
)
from app.utils.schema_validators import validate_text_value


def _validate_title(v):
    # A title is always required, so an explicit null is refused too.
    if v is None:
        raise ValueError("Event title is required.")
    return validate_text_value(
        v,
        field_label="Event title",
        min_length=EVENT_TITLE_MIN_LENGTH,
        max_length=EVENT_TITLE_MAX_LENGTH,
        allow_newlines=False,
    )


def _validate_description(v):
    # The description is optional; null clears it.
    if v is None:
        return None
    return validate_text_value(
        v,
        field_label="Event description",
        min_length=0,
        max_length=EVENT_DESCRIPTION_MAX_LENGTH,
    )


class EventCreateRequest(BaseModel):
    title: str
    description: Optional[str] = None
    category: Optional[str] = None
    cost: Optional[float] = 0
    max_capacity: Optional[int] = None
    start_datetime: datetime
    end_datetime: datetime
    location_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    @field_validator("title", mode="before")
    @classmethod
    def validate_title(cls, v):
        return _validate_title(v)

    @field_validator("description", mode="before")
    @classmethod
    def validate_description(cls, v):
        return _validate_description(v)


class EventUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    cost: Optional[float] = None
    max_capacity: Optional[int] = None
    start_datetime: Optional[datetime] = None
    end_datetime: Optional[datetime] = None
    location_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    status: Optional[str] = None

    # Validators only run on fields the client actually sent, so a partial
    # update that leaves out the title is still accepted.
    @field_validator("title", mode="before")
    @classmethod
    def validate_title(cls, v):
        return _validate_title(v)

    @field_validator("description", mode="before")
    @classmethod
    def validate_description(cls, v):
        return _validate_description(v)