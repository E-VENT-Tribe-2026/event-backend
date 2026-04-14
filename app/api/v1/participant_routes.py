from fastapi import APIRouter, Depends, HTTPException
from app.core.dependencies import get_current_user
from app.services.event_service import get_event
from app.db.supabase_client import supabase
from app.services.participant_service import (
    join_event,
    leave_event,
    get_event_participants,
    get_my_events
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

@router.delete("/{event_id}/participants/{participant_id}")
def remove_participant(event_id: str, participant_id: str, user=Depends(get_current_user)):
    event = get_event(event_id)

    if event["created_by"] != user.id:
        raise HTTPException(status_code=403, detail="Only the event owner can remove participants")

    supabase.table("event_participants") \
        .delete() \
        .eq("event_id", event_id) \
        .eq("user_id", participant_id) \
        .execute()

    return {"message": "Participant removed"}

@router.get("/my/events")
def my_events(user=Depends(get_current_user)):
    return get_my_events(user.id)

