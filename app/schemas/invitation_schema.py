from datetime import datetime
from typing import List, Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel

from app.schemas.profile_schema import UserSummary


class SendInvitation(BaseModel):
    event_id: UUID
    invitee_id: UUID


class InvitationItem(BaseModel):
    """Returned to the inviter after an invitation is sent."""
    invitation_id: int
    event_id: str
    created_at: Union[str, datetime]
    user: UserSummary


class InvitationEvent(BaseModel):
    id: str
    title: Optional[str] = None
    start_datetime: Optional[str] = None


class MyInvitation(BaseModel):
    """One invitation in the signed-in user's Invitations tab."""
    invitation_id: int
    created_at: Union[str, datetime]
    inviter: UserSummary
    event: InvitationEvent


class MyInvitationPage(BaseModel):
    page: int
    limit: int
    has_more: bool
    total: int
    data: List[MyInvitation]


class InvitableFriend(BaseModel):
    """A friend in the "Invite friends" window."""
    user: UserSummary
    invite_status: Literal["can_invite", "invited", "attending", "unavailable"]
    can_invite: bool


class InvitableFriendPage(BaseModel):
    page: int
    limit: int
    has_more: bool
    data: List[InvitableFriend]


class EventInvitationSummary(BaseModel):
    """Added to an event's details for the signed-in user."""
    invited: bool
    invited_by: Optional[UserSummary] = None
    other_inviters_count: int = 0


class MessageResponse(BaseModel):
    message: str