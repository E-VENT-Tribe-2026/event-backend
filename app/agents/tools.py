import uuid
from typing import Any, Optional


DRAFT_FIELDS = (
    "title",
    "description",
    "category",
    "cost",
    "max_capacity",
    "start_datetime",
    "end_datetime",
    "location_name",
    "latitude",
    "longitude",
)


def merge_draft(current: Optional[dict], updates: Optional[dict]) -> dict[str, Any]:
    """Overlay clarified fields onto the draft already in the conversation."""
    merged: dict[str, Any] = {}
    for source in (current or {}, updates or {}):
        if not isinstance(source, dict):
            continue
        for key in DRAFT_FIELDS:
            if key not in source:
                continue
            value = source[key]
            if value is None or value == "":
                continue
            merged[key] = value
    return merged


# TODO: This placeholder implementation will be replaced by importing and calling the service methods (e.g., `from app.services.event_details_service import get_event_details; return get_event_details(tool_input)`) once tickets #161, #163, and #164 are merged into dev.


def tool_search_events(tool_input: dict[str, Any]) -> dict[str, Any]:
    """Execute search_events tool; will be replaced by `from app.services.event_search_service import search_events; return search_events(tool_input)` once merged."""
    from app.services.event_search_service import search_events
    viewer_id = tool_input.get("user_id") if isinstance(tool_input.get("user_id"), str) else None
    return search_events({k: v for k, v in tool_input.items() if k != "user_id"}, viewer_id)

    return {
        "request_id": str(uuid.uuid4()),
        "success": True,
        "events": [],
        "pagination": {"page": 1, "limit": 10, "total": 0, "has_next": False},
        "error": None,
    }


def tool_get_event_details(tool_input: dict[str, Any]) -> dict[str, Any]:
    """Execute get_event_details tool; will be replaced by `from app.services.event_details_service import get_event_details; return get_event_details(tool_input)` once merged."""
    from app.services.event_details_service import get_event_details
    user_id = tool_input.get("user_id") if isinstance(tool_input.get("user_id"), str) else None
    return get_event_details({k: v for k, v in tool_input.items() if k != "user_id"}, user_id)

    return {
        "request_id": str(uuid.uuid4()),
        "success": True,
        "event": None,
        "error": None,
    }


def tool_draft_new_event(tool_input: dict[str, Any]) -> dict[str, Any]:
    """Execute draft_new_event tool; will be replaced by `from app.services.event_draft_service import draft_new_event; return draft_new_event(tool_input)` once merged."""
    from app.services.event_draft_service import draft_new_event
    user_id = tool_input.get("user_id") if isinstance(tool_input.get("user_id"), str) else None
    payload = merge_draft({}, tool_input)
    return draft_new_event(payload, user_id)

    return {
        "request_id": str(uuid.uuid4()),
        "success": True,
        "draft": {},
        "validation_issues": [],
        "error": None,
    }


TOOL_REGISTRY = {
    "search_events": tool_search_events,
    "get_event_details": tool_get_event_details,
    "draft_new_event": tool_draft_new_event,
}
