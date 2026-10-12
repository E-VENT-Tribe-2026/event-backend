from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query

from app.core.dependencies import get_current_onboarded_user
from app.core.input_limits import SEARCH_TEXT_MAX_LENGTH
from app.schemas.invitation_schema import (
    InvitableFriendPage,
    InvitationItem,
    MessageResponse,
    MyInvitationPage,
    SendInvitation,
)
from app.services.invitation_service import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    dismiss_invitation,
    get_invitable_friends,
    get_my_invitations,
    invite_friend,
)

router = APIRouter()

MAX_PAGE = 10000
MAX_INVITATION_ID = 9223372036854775807  # postgres bigint upper bound


@router.post("", status_code=201, response_model=InvitationItem)
def send_invitation(body: SendInvitation, user=Depends(get_current_onboarded_user)):
    """Invite one friend to an upcoming event the user organizes or joined."""
    return invite_friend(user.id, str(body.event_id), str(body.invitee_id))


@router.get("", response_model=MyInvitationPage)
def list_my_invitations(
    page: int = Query(1, ge=1, le=MAX_PAGE),
    limit: int = Query(DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    user=Depends(get_current_onboarded_user),
):
    """The signed-in user's invitations, newest first, with their total number."""
    return get_my_invitations(user.id, page, limit)


@router.get("/events/{event_id}/friends", response_model=InvitableFriendPage)
def list_invitable_friends(
    event_id: UUID,
    search: str | None = Query(None, max_length=SEARCH_TEXT_MAX_LENGTH),
    page: int = Query(1, ge=1, le=MAX_PAGE),
    limit: int = Query(DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    user=Depends(get_current_onboarded_user),
):
    """Friends for the "Invite friends" window, searchable by username."""
    return get_invitable_friends(user.id, str(event_id), search, page, limit)


@router.delete("/{invitation_id}", response_model=MessageResponse)
def dismiss(
    invitation_id: int = Path(..., ge=1, le=MAX_INVITATION_ID),
    user=Depends(get_current_onboarded_user),
):
    """Dismiss an invitation the user received. Only the invited user can do this."""
    return dismiss_invitation(user.id, invitation_id)