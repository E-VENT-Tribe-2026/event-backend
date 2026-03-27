from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class AttendeeProfile(BaseModel):
    id: str
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None


class AttendeeItem(BaseModel):
    user_id: str
    status: str
    created_at: Optional[datetime] = None
    profiles: Optional[AttendeeProfile] = None


class AttendeeListResponse(BaseModel):
    event_id: str
    attendee_count: int
    # None when the requesting user has not joined and is not the organizer
    attendees: Optional[List[AttendeeItem]] = None
    detail: Optional[str] = None


class RemoveParticipantResponse(BaseModel):
    message: str
    event_id: str
    removed_user_id: str