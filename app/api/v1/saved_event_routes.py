from fastapi import APIRouter, Depends
from app.core.dependencies import get_current_user
from app.services.saved_event_service import *
from app.services.event_service import attach_organizers

router = APIRouter()

@router.post("/save-events/{event_id}")
def save(event_id: str, user=Depends(get_current_user)):
    return save_event(user.id, event_id)

@router.delete("/unsave-events/{event_id}")
def unsave(event_id: str, user=Depends(get_current_user)):
    return remove_saved_event(user.id, event_id)

@router.get("/all")
def get_saved(user=Depends(get_current_user)):
    events = get_saved_events(user.id)
    attach_organizers(events)
    return events