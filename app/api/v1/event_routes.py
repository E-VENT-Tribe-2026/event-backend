from fastapi import APIRouter, Depends
from app.core.dependencies import get_current_user
from app.schemas.event_schema import EventCreate
from app.services.event_service import get_all_events, create_event

router = APIRouter()

@router.get("/")
def fetch_events():
    return get_all_events()

@router.post("/")
def add_event(
    event: EventCreate,
    user_id: str = Depends(get_current_user)
):
    return create_event(event.dict(), user_id=user_id)