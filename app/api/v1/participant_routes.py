from fastapi import APIRouter, Depends
from app.core.dependencies import get_current_user
from app.services.participant_service import (
    join_event,
    leave_event,
    get_event_attendees,
    remove_participant,
)

router = APIRouter()


@router.post("/{event_id}/join")
def join_event_api(
    event_id: str,
    user=Depends(get_current_user),
):
    """Join an event. Authenticated users only."""
    return join_event(user.id, event_id)


@router.post("/{event_id}/leave")
def leave_event_api(
    event_id: str,
    user=Depends(get_current_user),
):
    """Leave an event. Authenticated users only."""
    return leave_event(user.id, event_id)


@router.get("/{event_id}/participants")
def get_attendees_api(
    event_id: str,
    user=Depends(get_current_user),
):
    """
    Retrieve event attendees.

    - Organizer or joined users  → full attendee list + count
    - Everyone else              → attendee count only
    """
    return get_event_attendees(event_id, user.id)


@router.delete("/{event_id}/participants/{participant_id}")
def remove_participant_api(
    event_id: str,
    participant_id: str,
    user=Depends(get_current_user),
):
    """
    Remove a participant from an event.
    Only the event organizer can perform this action.
    """
    return remove_participant(user.id, event_id, participant_id)