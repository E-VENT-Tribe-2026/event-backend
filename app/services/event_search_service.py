import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from pydantic import ValidationError

from app.db.supabase_client import supabase
from app.schemas.event_search_schema import SearchEventsInput


logger = logging.getLogger(__name__)

_TEXT_FIELDS = ("query", "category", "date", "city")
_FIELD_MESSAGES = {
    "query": "Query must be a string of at most 200 characters.",
    "category": "Category must be a string of at most 100 characters.",
    "upcoming": "Upcoming must be a boolean.",
    "date": "Date must be a calendar date in YYYY-MM-DD format.",
    "city": "City must be a string of at most 120 characters.",
    "page": "Page must be an integer greater than or equal to 1.",
    "limit": "Limit must be an integer from 1 to 50.",
}
_SUMMARY_COLUMNS = (
    "id, title, description, category, cost, max_capacity, status, "
    "start_datetime, end_datetime, location_name"
)


class SearchInputError(Exception):
    def __init__(self, message: str, field: Optional[str]):
        self.message = message
        self.field = field


def search_events(payload: Any) -> dict:
    request_id = str(uuid.uuid4())
    try:
        criteria = _parse_input(payload)
    except SearchInputError as exc:
        return _failure(request_id, "INVALID_INPUT", exc.message, exc.field)

    try:
        events, total = _fetch_events(criteria)
    except Exception as exc:
        logger.error("Event search failed (type=%s)", type(exc).__name__)
        return _failure(
            request_id,
            "INTERNAL_ERROR",
            "Event search is temporarily unavailable.",
            None,
        )

    return {
        "request_id": request_id,
        "success": True,
        "events": events,
        "pagination": {
            "page": criteria.page,
            "limit": criteria.limit,
            "total": total,
            "has_next": criteria.page * criteria.limit < total,
        },
        "error": None,
    }


def _parse_input(payload: Any) -> SearchEventsInput:
    if not isinstance(payload, dict):
        raise SearchInputError("Search input must be an object.", None)

    normalized = dict(payload)
    for field in _TEXT_FIELDS:
        value = normalized.get(field)
        if isinstance(value, str):
            stripped = value.strip()
            normalized[field] = stripped or None

    try:
        return SearchEventsInput.model_validate(normalized)
    except ValidationError as exc:
        raise _input_error(exc) from None


def _input_error(exc: ValidationError) -> SearchInputError:
    err = exc.errors()[0]
    loc = [str(part) for part in err.get("loc", ())]
    field = loc[0] if loc else None
    if err.get("type") == "extra_forbidden":
        return SearchInputError("Unknown search field.", field)
    return SearchInputError(_FIELD_MESSAGES.get(field, "Invalid search input."), field)


def _fetch_events(criteria: SearchEventsInput) -> tuple[list[dict], int]:
    now = datetime.now(timezone.utc).isoformat()
    query = (
        supabase.table("events")
        .select(_SUMMARY_COLUMNS, count="exact")
        .eq("status", "active")
        .gte("end_datetime", now)
    )

    if criteria.upcoming:
        query = query.gt("start_datetime", now)
    if criteria.date is not None:
        day = date.fromisoformat(criteria.date)
        day_start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)
        query = query.gte("start_datetime", day_start.isoformat()).lt(
            "start_datetime", day_end.isoformat()
        )
    if criteria.category is not None:
        query = query.eq("category", criteria.category)
    if criteria.city is not None:
        query = query.ilike("location_name", _contains_pattern(criteria.city))
    if criteria.query is not None:
        pattern = _quote_filter_value(_contains_pattern(criteria.query))
        query = query.or_(f"title.ilike.{pattern},description.ilike.{pattern}")

    start = (criteria.page - 1) * criteria.limit
    end = start + criteria.limit - 1
    response = (
        query.order("start_datetime", desc=False)
        .order("id", desc=False)
        .range(start, end)
        .execute()
    )

    rows = response.data or []
    total = response.count if response.count is not None else len(rows)
    return [_summary(row) for row in rows], total


def _contains_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _quote_filter_value(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _summary(row: dict) -> dict:
    return {
        "id": _text(row.get("id")),
        "title": _text(row.get("title")),
        "description": _optional_text(row.get("description")),
        "category": _optional_text(row.get("category")),
        "start_datetime": _text(row.get("start_datetime")),
        "end_datetime": _optional_text(row.get("end_datetime")),
        "location_name": _optional_text(row.get("location_name")),
        "cost": None if row.get("cost") is None else float(row["cost"]),
        "max_capacity": None if row.get("max_capacity") is None else int(row["max_capacity"]),
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
        "events": [],
        "pagination": {"page": 1, "limit": 10, "total": 0, "has_next": False},
        "error": {"code": code, "message": message, "field": field},
    }
