from fastapi import APIRouter, Depends, Query
from app.core.dependencies import get_current_user
from app.services.participant_service import (
    join_event,
    leave_event,
    get_event_participants
)

router = APIRouter()

@router.post("/{event_id}/join")
def join_event_api(
    event_id: str,
    user = Depends(get_current_user)
):

    return join_event(user.id, event_id)


@router.post("/{event_id}/leave")
def leave_event_api(
    event_id: str,
    user = Depends(get_current_user)
):

    return leave_event(user.id, event_id)


@router.get("/{event_id}/participants")
def participants_api(event_id: str):

    return get_event_participants(event_id)