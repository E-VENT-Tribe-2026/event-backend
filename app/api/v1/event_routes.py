from fastapi import APIRouter, Depends, Query
from app.core.dependencies import get_current_user
from app.schemas.event_schema import EventCreateRequest, EventUpdateRequest
from app.services.event_service import (
    create_event,
    get_event,
    update_event,
    delete_event,
    list_events,
    get_events_by_user,
)

router = APIRouter()


# IMPORTANT: Static routes (/me, /my) must be declared BEFORE dynamic routes (/{event_id})
# to prevent FastAPI from treating "me" as an event_id.

@router.get("/my")
def get_my_events(
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=50),
    user=Depends(get_current_user)
):
    """Returns all events created by the authenticated user."""
    return get_events_by_user(user.id, page, limit)

@router.get("/my-events")
def get_all_my_events(user=Depends(get_current_user)):
    """Dedicated endpoint to get ALL events for the logged-in user."""
    print("USER OBJECT:", user)
    return {"debug": user}
    
@router.get("/")
def get_events(
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=50),
    category: str | None = None,
    upcoming: bool = False,
    search: str | None = None,
):
    """List events with optional filters. Public endpoint."""
    return list_events(page, limit, category, upcoming, search)


@router.post("/")
def create_new_event(
    data: EventCreateRequest,
    user=Depends(get_current_user)
):
    """Create a new event. Authenticated users only."""
    # CHANGE: Add mode="json" to convert datetimes to strings
    return create_event(user.id, data.model_dump(mode="json"))


@router.put("/{event_id}")
def update_existing_event(
    event_id: str,
    data: EventUpdateRequest,
    user=Depends(get_current_user)
):
    """Update an event. Only the creator can update."""
    # CHANGE: Add mode="json" here as well
    return update_event(user.id, event_id, data.model_dump(mode="json", exclude_unset=True))


@router.get("/{event_id}")
def read_event(event_id: str):
    """Get a single event by ID. Public endpoint."""
    return get_event(event_id)


@router.delete("/{event_id}")
def delete_existing_event(
    event_id: str,
    user=Depends(get_current_user)
):
    """Delete an event. Only the creator can delete."""
    return delete_event(user.id, event_id)
