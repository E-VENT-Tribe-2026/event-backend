from fastapi import APIRouter, Depends, Query
from app.core.dependencies import get_current_user
from app.schemas.event_schema import EventCreateRequest, EventUpdateRequest
from app.services.event_service import ( get_all_events, 
                                        create_event, 
                                        get_event,
                                        update_event,
                                        delete_event,
                                        list_events )

router = APIRouter()

@router.post("/")
def create_new_event(
    data: EventCreateRequest,
    user_id: str = Depends(get_current_user)
):
    return create_event(user_id, data.model_dump())

@router.get("/{event_id}")
def read_event(event_id: str):
    return get_event(event_id)


@router.put("/{event_id}")
def update_existing_event(
    event_id: str,
    data: EventUpdateRequest,
    user_id: str = Depends(get_current_user)
):
    return update_event(user_id, event_id, data.model_dump(exclude_unset=True))

@router.delete("/{event_id}")
def delete_existing_event(
    event_id: str,
    user_id: str = Depends(get_current_user)
):
    return delete_event(user_id, event_id)

@router.get("/")
def get_events(
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=50),
    category: str | None = None,
    upcoming: bool = False,
    search: str | None = None
):
    return list_events(page, limit, category, upcoming, search)
