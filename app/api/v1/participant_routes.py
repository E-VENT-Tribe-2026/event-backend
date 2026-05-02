from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from app.core.dependencies import get_current_user
from app.services.event_service import get_event
from app.db.supabase_client import supabase
from app.services.participant_service import (
    join_event,
    _join_side_effects,
    leave_event,
    get_event_participants,
    get_my_events,
    remove_participant,
)

router = APIRouter()

@router.post("/{event_id}/join")
def join_event_api(
    event_id: str,
    background_tasks: BackgroundTasks,
    user=Depends(get_current_user)
):
    data, event = join_event(user.id, event_id)
    background_tasks.add_task(_join_side_effects, user.id, event_id, event)
    return data


@router.post("/{event_id}/leave")
def leave_event_api(
    event_id: str,
    user = Depends(get_current_user)
):

    return leave_event(user.id, event_id)


@router.get("/{event_id}/participants")
def participants_api(event_id: str):
    return get_event_participants(event_id)


@router.get("/{event_id}/participants/count")
def participants_count_api(event_id: str):
    participants = get_event_participants(event_id)
    return {"event_id": event_id, "count": len(participants)}


@router.get("/{event_id}/my-status")
def my_status_api(event_id: str, user=Depends(get_current_user)):
    response = (
        supabase.table("event_participants")
        .select("status")
        .eq("event_id", event_id)
        .eq("user_id", user.id)
        .execute()
    )
    if response.data:
        return {"joined": True, "status": response.data[0]["status"]}
    return {"joined": False, "status": None}

@router.delete("/{event_id}/participants/{participant_id}")
def remove_participant_api(event_id: str, participant_id: str, user=Depends(get_current_user)):
    return remove_participant(user.id, event_id, participant_id)

@router.get("/my/events")
def my_events(user=Depends(get_current_user)):
    return get_my_events(user.id)

