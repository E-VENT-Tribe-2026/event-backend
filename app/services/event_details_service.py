import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import ValidationError

from app.db.supabase_client import supabase
from app.schemas.event_details_schema import EventDetailsInput


logger = logging.getLogger(__name__)

_DETAIL_COLUMNS = (
    "id, title, description, category, cost, max_capacity, status, "
    "start_datetime, end_datetime, location_name, latitude, longitude, created_by"
)
_FIELD_MESSAGES = {
    "event_id": "Event ID must be a UUID.",
}


class EventDetailsInputError(Exception):
    def __init__(self, message: str, field: Optional[str]):
        self.message = message
        self.field = field


def get_event_details(payload: Any, user_id: Optional[str]) -> dict:
    request_id = str(uuid.uuid4())
    if not isinstance(user_id, str) or not user_id.strip():
        return _failure(request_id, "UNAUTHORIZED", "Authentication is required.", None)

    try:
        criteria = _parse_input(payload)
    except EventDetailsInputError as exc:
        return _failure(request_id, "INVALID_INPUT", exc.message, exc.field)

    try:
        row = _fetch_event(criteria.event_id)
    except Exception as exc:
        logger.error("Event details lookup failed (type=%s)", type(exc).__name__)
        return _failure(
            request_id,
            "INTERNAL_ERROR",
            "Event details are temporarily unavailable.",
            None,
        )

    if row is None:
        return _failure(request_id, "NOT_FOUND", "Event not found.", "event_id")

    if not _is_visible(row):
        return _failure(request_id, "FORBIDDEN", "You cannot view this event.", None)

    return {
        "request_id": request_id,
        "success": True,
        "event": _details(row),
        "error": None,
    }


def _parse_input(payload: Any) -> EventDetailsInput:
    if not isinstance(payload, dict):
        raise EventDetailsInputError("Event details input must be an object.", None)

    normalized = dict(payload)
    event_id = normalized.get("event_id")
    if isinstance(event_id, str):
        normalized["event_id"] = event_id.strip()
        if not normalized["event_id"]:
            raise EventDetailsInputError("Event ID is required.", "event_id")

    try:
        return EventDetailsInput.model_validate(normalized)
    except ValidationError as exc:
        raise _input_error(exc) from None


def _input_error(exc: ValidationError) -> EventDetailsInputError:
    err = exc.errors()[0]
    loc = [str(part) for part in err.get("loc", ())]
    field = loc[0] if loc else None
    if err.get("type") == "extra_forbidden":
        return EventDetailsInputError("Unknown field.", field)
    if err.get("type") == "missing":
        return EventDetailsInputError("Event ID is required.", "event_id")
    return EventDetailsInputError(
        _FIELD_MESSAGES.get(field, "Invalid event details input."),
        field,
    )


def _fetch_event(event_id: str) -> Optional[dict]:
    response = (
        supabase.table("events")
        .select(_DETAIL_COLUMNS)
        .eq("id", event_id)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    if not rows:
        return None
    return rows[0]


def _is_visible(row: dict) -> bool:
    if row.get("status") != "active":
        return False
    end = _as_datetime(row.get("end_datetime"))
    if end is None:
        return False
    return end >= datetime.now(timezone.utc)


def _as_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _details(row: dict) -> dict:
    return {
        "id": _text(row.get("id")),
        "title": _text(row.get("title")),
        "description": _optional_text(row.get("description")),
        "category": _optional_text(row.get("category")),
        "cost": None if row.get("cost") is None else float(row["cost"]),
        "max_capacity": None if row.get("max_capacity") is None else int(row["max_capacity"]),
        "start_datetime": _optional_text(row.get("start_datetime")),
        "end_datetime": _optional_text(row.get("end_datetime")),
        "location_name": _optional_text(row.get("location_name")),
        "latitude": None if row.get("latitude") is None else float(row["latitude"]),
        "longitude": None if row.get("longitude") is None else float(row["longitude"]),
        "created_by": _optional_text(row.get("created_by")),
        "status": _text(row.get("status")),
    }


def _text(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None:
        return ""
    return str(value)


def _optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    return _text(value)


def _failure(request_id: str, code: str, message: str, field: Optional[str]) -> dict:
    return {
        "request_id": request_id,
        "success": False,
        "event": None,
        "error": {"code": code, "message": message, "field": field},
    }
