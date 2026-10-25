import logging
import time

from fastapi import APIRouter, Depends, Query, BackgroundTasks, File, UploadFile
from app.core.dependencies import get_current_user, get_current_onboarded_user, get_optional_user
from app.core.input_limits import SEARCH_TEXT_MAX_LENGTH
from app.schemas.event_schema import EventCreateRequest, EventUpdateRequest
from app.schemas.check_in_schema import CheckInRequest, CheckInResponse, CheckInCodeResponse, CheckInListResponse
from fastapi import HTTPException
from app.db.supabase_client import supabase
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
from app.services.check_in_service import (
    check_in as record_event_check_in,
    get_event_check_in_code,
    list_event_check_ins,
)


router = APIRouter()
logger = logging.getLogger(__name__)

# Same allowlist as profile photos — event banners go in the "avatars" bucket.
ALLOWED_BANNER_EXTENSIONS = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


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


@router.post("/upload-banner")
async def upload_event_banner(
    file: UploadFile = File(...),
    user=Depends(get_current_onboarded_user),
):
    """Upload an event banner photo to the avatars bucket and return its public URL."""
    try:
        file_ext = file.filename.split(".")[-1].lower() if file.filename and "." in file.filename else ""
        content_type = ALLOWED_BANNER_EXTENSIONS.get(file_ext)
        if not content_type:
            raise HTTPException(
                status_code=400,
                detail="Unsupported file format. Please upload a JPG, PNG, or WEBP image.",
            )

        file_path = f"{user.id}/event-banner-{int(time.time())}.{file_ext}"
        file_bytes = await file.read()

        supabase.storage.from_("avatars").upload(
            path=file_path,
            file=file_bytes,
            file_options={"content-type": content_type, "upsert": "true"},
        )

        public_url_res = supabase.storage.from_("avatars").get_public_url(file_path)
        public_url = public_url_res if isinstance(public_url_res, str) else public_url_res.get("publicUrl")
        if not public_url:
            raise HTTPException(status_code=500, detail="Failed to generate public URL for photo.")

        return {"banner": public_url, "banner_url": public_url}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Event banner upload failed for user {user.id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not upload event banner.")


@router.get("")
@router.get("/")
def get_events(
    page: int = Query(1),
    limit: int = Query(10),
    category: str | None = Query(None, max_length=SEARCH_TEXT_MAX_LENGTH),
    upcoming: bool = False,
    search: str | None = Query(None, max_length=SEARCH_TEXT_MAX_LENGTH),
    date: str | None = None,
    event_date: str | None = Query(None),
    city: str | None = Query(None, max_length=SEARCH_TEXT_MAX_LENGTH),
    user=Depends(get_optional_user),
):
    viewer_id = user.id if user is not None else None
    result = list_events(
        page, limit, category, upcoming, search, date or event_date, city, viewer_id=viewer_id
    )
    attach_organizers(result.get("data") or [])
    if user is not None:
        attach_friends_attending_count(result.get("data") or [], user.id)
    return result


@router.post("")
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


@router.get("/{event_id}/check-in-code", response_model=CheckInCodeResponse)
def read_event_check_in_code(event_id: str, user=Depends(get_current_onboarded_user)):
    """Organizer only: the six-digit door code and the QR content (the same code)."""
    return get_event_check_in_code(event_id, user.id)


@router.post("/{event_id}/check-in", response_model=CheckInResponse)
def post_event_check_in(
    event_id: str,
    data: CheckInRequest,
    user=Depends(get_current_onboarded_user),
):
    """Participant check-in with the typed six-digit code or the scanned QR content."""
    return record_event_check_in(
        event_id,
        user.id,
        code=data.code,
        qr_content=data.qr_content,
    )


@router.get(
    "/{event_id}/check-ins",
    response_model=CheckInListResponse,
    response_model_exclude_none=True,
)
def read_event_check_ins(event_id: str, user=Depends(get_current_onboarded_user)):
    """Who has checked in. Times are included only for the organizer."""
    return list_event_check_ins(event_id, user.id)


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



