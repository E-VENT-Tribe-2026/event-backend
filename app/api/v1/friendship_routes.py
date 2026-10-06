from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query
from app.core.dependencies import get_current_user, get_current_onboarded_user
from app.services.friendship_service import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    send_friend_request,
    get_incoming_requests,
    get_sent_requests,
    count_incoming_requests,
    accept_friend_request,
    decline_friend_request,
    cancel_friend_request,
    get_friends,
    remove_friend,
    get_friend_suggestions,
)
from app.schemas.friendship_schema import (
    FriendItem,
    FriendPage,
    FriendRequestCount,
    FriendRequestItem,
    FriendRequestPage,
    MessageResponse,
    SendFriendRequest,
    SuggestionPage,
)

router = APIRouter()

MAX_PAGE = 10000
MAX_REQUEST_ID = 9223372036854775807  # postgres bigint upper bound


@router.post("/requests", status_code=201, response_model=FriendRequestItem)
def send_request(body: SendFriendRequest, user=Depends(get_current_user)):
    return send_friend_request(user.id, str(body.receiver_id))


@router.get("/requests/incoming", response_model=FriendRequestPage)
def incoming_requests(
    page: int = Query(1, ge=1, le=MAX_PAGE),
    limit: int = Query(DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    user=Depends(get_current_user),
):
    return get_incoming_requests(user.id, page, limit)


@router.get("/requests/sent", response_model=FriendRequestPage)
def sent_requests(
    page: int = Query(1, ge=1, le=MAX_PAGE),
    limit: int = Query(DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    user=Depends(get_current_user),
):
    return get_sent_requests(user.id, page, limit)


@router.get("/requests/count", response_model=FriendRequestCount)
def incoming_requests_count(user=Depends(get_current_user)):
    return count_incoming_requests(user.id)


@router.post("/requests/{request_id}/accept", response_model=FriendItem)
def accept_request(request_id: int = Path(..., ge=1, le=MAX_REQUEST_ID), user=Depends(get_current_user)):
    return accept_friend_request(request_id, user.id)


@router.post("/requests/{request_id}/decline", response_model=MessageResponse)
def decline_request(request_id: int = Path(..., ge=1, le=MAX_REQUEST_ID), user=Depends(get_current_user)):
    return decline_friend_request(request_id, user.id)


@router.delete("/requests/{request_id}", response_model=MessageResponse)
def cancel_request(request_id: int = Path(..., ge=1, le=MAX_REQUEST_ID), user=Depends(get_current_user)):
    return cancel_friend_request(request_id, user.id)


@router.get("", response_model=FriendPage)
def list_friends(
    page: int = Query(1, ge=1, le=MAX_PAGE),
    limit: int = Query(DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    user=Depends(get_current_user),
):
    return get_friends(user.id, page, limit)


@router.delete("/{friend_id}", response_model=MessageResponse)
def unfriend(friend_id: UUID, user=Depends(get_current_user)):
    return remove_friend(user.id, str(friend_id))


@router.get("/suggestions", response_model=SuggestionPage)
def get_suggestions(
    page: int = Query(1, ge=1, le=MAX_PAGE),
    limit: int = Query(DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    user=Depends(get_current_onboarded_user),
):
    """Get list of users who are not yet friends and have no active requests."""
    return get_friend_suggestions(user.id, page, limit)