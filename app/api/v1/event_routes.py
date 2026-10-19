import logging

from fastapi import APIRouter, Depends, Query, BackgroundTasks
from app.core.dependencies import get_current_user, get_current_onboarded_user, get_optional_user
from app.core.input_limits import SEARCH_TEXT_MAX_LENGTH
from app.schemas.event_schema import EventCreateRequest, EventUpdateRequest
from fastapi import HTTPException
from app.services import event_service
from app.services.event_service import (
    create_event,
    get_event,
    update_event,
    delete_event,
    list_events,
    get_all_events_by_user,
    get_max_event_price,
    _update_event_side_effects,
    attach_organizers,
)
from app.services.invitation_service import get_invitation_summary
from app.services.block_visibility import is_event_hidden
from app.services.participant_service import attach_friends_attending_count


router = APIRouter()
logger = logging.getLogger(__name__)


# IMPORTANT: Static routes (/me, /my) must be declared BEFORE dynamic routes (/{event_id})
# to prevent FastAPI from treating "me" as an event_id.
# The /my-events route is kept separate to avoid limiter issues with the /my route, which is more likely to be used frequently by the same user.

'''@router.get("/my")
def get_my_events(
    page: int = Query(1, ge=1),
    limit: int = Query(10, le=50),
    user=Depends(get_current_user)
):
    """Returns all events created by the authenticated user."""
    return get_events_by_user(user.id, page, limit)
'''
@router.get("/max-price")
def read_max_price():
    # This 'uses' the function, which will clear the 'not accessed' warning
    max_price = get_max_event_price()
    return {"max_price": max_price}

@router.get("/my-events")
def get_all_my_events(user=Depends(get_current_onboarded_user)):
    """Return all events created by the logged-in user."""

    user_id = getattr(user, "id", None) or user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid user")

    try:
        events_response = get_all_events_by_user(user_id)
        attach_organizers(events_response.get("data") or [])
        return events_response

    except Exception as e:
        logger.error(f"Internal error in /my-events for user {user_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Could not fetch events for user"
        )


@router.get("/")
def get_events(
    page: int = Query(1),
    limit: int = Query(10),
    category: str | None = Query(None, max_length=SEARCH_TEXT_MAX_LENGTH),
    upcoming: bool = False,
    search: str | None = Query(None, max_length=SEARCH_TEXT_MAX_LENGTH),
    date: str | None = None,
    city: str | None = Query(None, max_length=SEARCH_TEXT_MAX_LENGTH),
    user=Depends(get_optional_user),
):
    viewer_id = user.id if user is not None else None
    result = list_events(page, limit, category, upcoming, search, date, city, viewer_id=viewer_id)
    attach_organizers(result.get("data") or [])
    if user is not None:
        attach_friends_attending_count(result.get("data") or [], user.id)
    return result


@router.post("/")
def create_new_event(
    data: EventCreateRequest,
    user=Depends(get_current_onboarded_user)
):
    """Create a new event. Authenticated users only."""
    # CHANGE: Add mode="json" to convert datetimes to strings
    return create_event(user.id, data.model_dump(mode="json"))


@router.put("/{event_id}")
def update_existing_event(
    event_id: str,
    data: EventUpdateRequest,
    background_tasks: BackgroundTasks,
    user=Depends(get_current_onboarded_user)
):
    """Update an event. Only the creator can update."""
    result, original_event, updated_event = update_event(
        user.id, event_id, data.model_dump(mode="json", exclude_unset=True)
    )
    background_tasks.add_task(_update_event_side_effects, user.id, event_id, original_event, updated_event)
    return result


@router.get("/{event_id}")
def read_event(event_id: str, user=Depends(get_optional_user)):
    """Get a single event by ID. Public endpoint.

    For a signed-in user, invitation says whether they were invited to the event (#186).
    """
    event = get_event(event_id)
    # An event organized by a user the viewer blocked, or who blocked the viewer, is not found.
    if user is not None and is_event_hidden(event, user.id):
        raise HTTPException(status_code=404, detail="Event not found")
    attach_organizers([event])
    if user is not None:
        try:
            event["invitation"] = get_invitation_summary(user.id, event)
        except Exception:
            logger.error(f"Invitation lookup failed for event {event_id}", exc_info=True)
            event["invitation"] = None
    return event


@router.delete("/{event_id}")
def delete_existing_event(
    event_id: str,
    user=Depends(get_current_onboarded_user)
):
    """Delete an event. Direct deletion is refused; events must be cancelled instead."""
    return delete_event(user.id, event_id)

@router.patch("/{event_id}/cancel")
@router.post("/{event_id}/cancel")
def cancel_existing_event(event_id: str, user=Depends(get_current_onboarded_user)):
    from app.services.event_service import cancel_event
    return cancel_event(user.id, event_id)



