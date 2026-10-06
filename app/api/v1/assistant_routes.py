from typing import Any

from fastapi import APIRouter, Body, Depends

from app.core.dependencies import get_current_user
from app.schemas.assistant_schema import AssistantChatRequest, AssistantChatResponse
from app.schemas.event_details_schema import EventDetailsResponse
from app.schemas.event_draft_schema import DraftNewEventResponse
from app.schemas.event_search_schema import SearchEventsResponse
from app.services.assistant_service import generate_reply
from app.services.event_details_service import get_event_details
from app.services.event_draft_service import draft_new_event
from app.services.event_search_service import search_events


router = APIRouter()


@router.post("/chat", response_model=AssistantChatResponse)
def chat(body: AssistantChatRequest, _user=Depends(get_current_user)):
    return AssistantChatResponse(reply=generate_reply(body.messages))


@router.post("/tools/search-events", response_model=SearchEventsResponse)
def search_events_tool(body: Any = Body(...), _user=Depends(get_current_user)):
    return search_events(body)


@router.post("/tools/event-details", response_model=EventDetailsResponse)
def event_details_tool(body: Any = Body(...), user=Depends(get_current_user)):
    return get_event_details(body, getattr(user, "id", None))


@router.post("/tools/draft-event", response_model=DraftNewEventResponse)
def draft_event_tool(body: Any = Body(...), user=Depends(get_current_user)):
    return draft_new_event(body, getattr(user, "id", None))