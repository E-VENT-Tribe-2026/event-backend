from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from uuid import UUID


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