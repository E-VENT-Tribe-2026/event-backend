from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from uuid import UUID

class EventCreate(BaseModel):
    title: str
    description: Optional[str] = None
    category: Optional[str] = None
    cost: Optional[float] = 0.0
    max_capacity: Optional[int] = None
    start_datetime: Optional[datetime] = None
    end_datetime: Optional[datetime] = None
    location_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None