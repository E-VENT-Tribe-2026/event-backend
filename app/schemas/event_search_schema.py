from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SearchEventsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    query: Optional[str] = Field(default=None, max_length=200)
    category: Optional[str] = Field(default=None, max_length=100)
    upcoming: bool = True
    date: Optional[str] = Field(default=None, pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
    city: Optional[str] = Field(default=None, max_length=120)
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=10, ge=1, le=50)

    @field_validator("date")
    @classmethod
    def date_must_be_a_real_day(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        date.fromisoformat(value)
        return value


class SearchEventSummary(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    category: Optional[str] = None
    start_datetime: str
    end_datetime: Optional[str] = None
    location_name: Optional[str] = None
    cost: Optional[float] = None
    max_capacity: Optional[int] = None
    status: str


class SearchEventsPagination(BaseModel):
    page: int = Field(ge=1)
    limit: int = Field(ge=1)
    total: int = Field(ge=0)
    has_next: bool


class SearchEventsError(BaseModel):
    code: str
    message: str
    field: Optional[str] = None


class SearchEventsResponse(BaseModel):
    request_id: str = Field(min_length=1)
    success: bool
    events: list[SearchEventSummary]
    pagination: SearchEventsPagination
    error: Optional[SearchEventsError] = None
