import logging
import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import ValidationError

from app.schemas.event_draft_schema import DraftNewEventInput, ValidationIssue


logger = logging.getLogger(__name__)

_TEXT_FIELDS = ("title", "description", "category", "location_name", "start_datetime", "end_datetime")
_ALLOWED_FIELDS = {
    "title", "description", "category", "cost", "max_capacity",
    "start_datetime", "end_datetime", "location_name", "latitude", "longitude"
}


def draft_new_event(payload: Any, user_id: Optional[str] = None) -> dict:
    """
    Validate structured event draft input and return a normalized preview.
    Preview-only flow: does NOT persist to database, notify participants, or invoke AI models.
    """
    request_id = str(uuid.uuid4())

    if user_id is not None and (not isinstance(user_id, str) or not user_id.strip()):
        return _failure(request_id, "UNAUTHORIZED", "Authentication is required.", None)

    if not isinstance(payload, dict):
        return _failure(request_id, "INVALID_INPUT", "Draft input must be an object.", None)

    # Check for unknown extra fields
    extra_fields = set(payload.keys()) - _ALLOWED_FIELDS
    if extra_fields:
        return _failure(
            request_id,
            "INVALID_INPUT",
            f"Unknown field: {next(iter(extra_fields))}",
            next(iter(extra_fields)),
        )

    normalized = dict(payload)
    for field in _TEXT_FIELDS:
        val = normalized.get(field)
        if isinstance(val, str):
            stripped = val.strip()
            normalized[field] = stripped if field in ("title", "start_datetime", "end_datetime") else (stripped or None)

    validation_issues: list[dict] = []

    # Validate schema fields
    parsed_input: Optional[DraftNewEventInput] = None
    try:
        parsed_input = DraftNewEventInput.model_validate(normalized)
    except ValidationError as exc:
        for err in exc.errors():
            loc = err.get("loc", ())
            field_name = str(loc[0]) if loc else None
            msg = err.get("msg", "Invalid field.")
            code = "REQUIRED_FIELD_MISSING" if err.get("type") == "missing" else "INVALID_INPUT"
            validation_issues.append({
                "code": code,
                "field": field_name,
                "message": msg,
                "severity": "error",
            })

    # Logical validation: date order check (end > start)
    start_dt = None
    end_dt = None
    if parsed_input:
        try:
            start_dt = datetime.fromisoformat(parsed_input.start_datetime.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(parsed_input.end_datetime.replace("Z", "+00:00"))
            if end_dt <= start_dt:
                validation_issues.append({
                    "code": "INVALID_DATE_ORDER",
                    "field": "end_datetime",
                    "message": "End datetime must be later than start datetime.",
                    "severity": "error",
                })
        except ValueError:
            pass

    has_errors = any(issue.get("severity") == "error" for issue in validation_issues)

    if has_errors or not parsed_input:
        return {
            "request_id": request_id,
            "success": False,
            "draft": None,
            "validation_issues": validation_issues,
            "error": {"code": "INVALID_INPUT", "message": "Draft validation failed.", "field": None},
        }

    # Normalized preview output
    draft_preview = {
        "title": parsed_input.title,
        "description": parsed_input.description,
        "category": parsed_input.category,
        "cost": float(parsed_input.cost) if parsed_input.cost is not None else 0.0,
        "max_capacity": parsed_input.max_capacity,
        "start_datetime": parsed_input.start_datetime,
        "end_datetime": parsed_input.end_datetime,
        "location_name": parsed_input.location_name,
        "latitude": parsed_input.latitude,
        "longitude": parsed_input.longitude,
    }

    return {
        "request_id": request_id,
        "success": True,
        "draft": draft_preview,
        "validation_issues": [],
        "error": None,
    }


def _failure(request_id: str, code: str, message: str, field: Optional[str]) -> dict:
    return {
        "request_id": request_id,
        "success": False,
        "draft": None,
        "validation_issues": [],
        "error": {"code": code, "message": message, "field": field},
    }
