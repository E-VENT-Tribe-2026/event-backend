"""Checks the JSON schemas in docs/agent-tool-specification.md.

The schemas are read straight from the document, so these tests fail if the
document changes in a way that breaks the rules agreed for sign-off.
"""
import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

SPEC_PATH = Path(__file__).resolve().parents[1] / "docs" / "agent-tool-specification.md"


def _load_schemas() -> dict:
    text = SPEC_PATH.read_text(encoding="utf-8")
    schemas = {}
    for block in re.findall(r"```json\n(.*?)\n```", text, flags=re.DOTALL):
        schema = json.loads(block)
        schemas[schema["title"]] = schema
    return schemas


SCHEMAS = _load_schemas()


def _validator(title: str) -> Draft202012Validator:
    schema = SCHEMAS[title]
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


def _is_valid(title: str, instance) -> bool:
    return _validator(title).is_valid(instance)


EVENT_ID = "3f2b8c1e-4d5a-4b6c-8e7f-9a0b1c2d3e4f"
ERROR = {"code": "INVALID_INPUT", "message": "Invalid search input.", "field": None}
EMPTY_PAGE = {"page": 1, "limit": 10, "total": 0, "has_next": False}


def test_all_six_schemas_are_present_and_well_formed():
    expected = {
        "SearchEventsInput", "SearchEventsOutput",
        "GetEventDetailsInput", "GetEventDetailsOutput",
        "DraftNewEventInput", "DraftNewEventOutput",
    }
    assert expected <= set(SCHEMAS)
    for title in expected:
        Draft202012Validator.check_schema(SCHEMAS[title])


def test_spec_uses_the_real_publish_endpoint():
    text = SPEC_PATH.read_text(encoding="utf-8")
    assert "/api/v1/events" not in text
    assert "POST /api/events/" in text


# --- Search input ---------------------------------------------------------

@pytest.mark.parametrize("payload", [
    {},
    {"query": None},
    {"query": "   "},
    {"upcoming": True, "page": 2, "limit": 20},
    {"query": None, "category": None, "date": None, "city": None},
    {"date": "2026-99-99"},
    {"date": "2026-02-30"},
    {"date": "26-1-1"},
    {"query": "jazz", "limit": 51},
    {"query": "jazz", "page": 0},
    {"query": "jazz", "user_id": EVENT_ID},
])
def test_search_input_rejects_invalid_or_unconstrained(payload):
    assert not _is_valid("SearchEventsInput", payload)


@pytest.mark.parametrize("payload", [
    {"query": "jazz"},
    {"city": "Bremen"},
    {"category": "Music", "upcoming": False},
    {"date": "2028-02-29"},
    {"query": None, "city": "Bremen", "page": 2, "limit": 50},
])
def test_search_input_accepts_constrained_searches(payload):
    assert _is_valid("SearchEventsInput", payload)


# --- Search output --------------------------------------------------------

def test_search_failure_with_null_error_is_rejected():
    response = {"request_id": "request-1", "success": False,
                "events": [], "pagination": EMPTY_PAGE, "error": None}
    assert not _is_valid("SearchEventsOutput", response)


def test_search_success_with_error_is_rejected():
    response = {"request_id": "request-1", "success": True,
                "events": [], "pagination": EMPTY_PAGE, "error": ERROR}
    assert not _is_valid("SearchEventsOutput", response)


def test_search_failure_with_events_is_rejected():
    event = {"id": EVENT_ID, "title": "Jazz night",
             "start_datetime": "2026-11-01T19:00:00+01:00", "status": "active"}
    response = {"request_id": "request-1", "success": False, "events": [event],
                "pagination": {"page": 1, "limit": 10, "total": 1, "has_next": False},
                "error": ERROR}
    assert not _is_valid("SearchEventsOutput", response)


def test_search_valid_success_and_failure():
    success = {"request_id": "request-1", "success": True, "events": [],
               "pagination": EMPTY_PAGE, "error": None}
    failure = {"request_id": "request-1", "success": False, "events": [],
               "pagination": EMPTY_PAGE, "error": ERROR}
    assert _is_valid("SearchEventsOutput", success)
    assert _is_valid("SearchEventsOutput", failure)


def test_search_output_rejects_cancelled_events_and_unknown_codes():
    cancelled = {"id": EVENT_ID, "title": "Jazz night",
                 "start_datetime": "2026-11-01T19:00:00+01:00", "status": "cancelled"}
    response = {"request_id": "r", "success": True, "events": [cancelled],
                "pagination": {"page": 1, "limit": 10, "total": 1, "has_next": False},
                "error": None}
    assert not _is_valid("SearchEventsOutput", response)

    bad_code = {"request_id": "r", "success": False, "events": [], "pagination": EMPTY_PAGE,
                "error": {"code": "DB_EXPLODED", "message": "x", "field": None}}
    assert not _is_valid("SearchEventsOutput", bad_code)


# --- Details --------------------------------------------------------------

DETAILS = {
    "id": EVENT_ID, "title": "Jazz night", "description": None, "category": "Music",
    "cost": 0, "max_capacity": None, "start_datetime": "2026-11-01T19:00:00+01:00",
    "end_datetime": "2026-11-01T22:00:00+01:00", "location_name": "Bremen",
    "latitude": None, "longitude": None, "created_by": None, "status": "active",
}


@pytest.mark.parametrize("payload", [{}, {"event_id": ""}, {"event_id": "abc"},
                                     {"event_id": EVENT_ID, "user_id": EVENT_ID}])
def test_details_input_rejects_bad_ids(payload):
    assert not _is_valid("GetEventDetailsInput", payload)


def test_details_output_success_and_error_are_consistent():
    ok = {"request_id": "r", "success": True, "event": DETAILS, "error": None}
    not_found = {"request_id": "r", "success": False, "event": None,
                 "error": {"code": "NOT_FOUND", "message": "Event not found.", "field": "event_id"}}
    assert _is_valid("GetEventDetailsOutput", ok)
    assert _is_valid("GetEventDetailsOutput", not_found)

    assert not _is_valid("GetEventDetailsOutput", {**ok, "event": None})
    assert not _is_valid("GetEventDetailsOutput", {**ok, "error": ERROR})
    assert not _is_valid("GetEventDetailsOutput", {**not_found, "error": None})
    assert not _is_valid("GetEventDetailsOutput", {**not_found, "event": DETAILS})


# --- Draft ----------------------------------------------------------------

DRAFT_INPUT = {"title": "Jazz night",
               "start_datetime": "2026-11-01T19:00:00+01:00",
               "end_datetime": "2026-11-01T22:00:00Z"}
PREVIEW = {"title": "Jazz night", "description": None, "category": None, "cost": None,
           "max_capacity": None, "start_datetime": "2026-11-01T19:00:00+01:00",
           "end_datetime": "2026-11-01T22:00:00Z", "location_name": None,
           "latitude": None, "longitude": None}


def test_draft_input_requires_timezone_and_real_title():
    assert _is_valid("DraftNewEventInput", DRAFT_INPUT)
    assert not _is_valid("DraftNewEventInput", {**DRAFT_INPUT, "start_datetime": "2026-11-01T19:00"})
    assert not _is_valid("DraftNewEventInput", {**DRAFT_INPUT, "title": "   "})
    assert not _is_valid("DraftNewEventInput", {**DRAFT_INPUT, "created_by": EVENT_ID})


def test_draft_output_success_and_error_are_consistent():
    ok = {"request_id": "r", "success": True, "draft": PREVIEW,
          "validation_issues": [], "error": None}
    issue = {"code": "INVALID_DATE_ORDER", "field": "end_datetime",
             "message": "End datetime must be later than start datetime.", "severity": "error"}
    failed = {"request_id": "r", "success": False, "draft": None,
              "validation_issues": [issue], "error": ERROR}
    assert _is_valid("DraftNewEventOutput", ok)
    assert _is_valid("DraftNewEventOutput", failed)

    assert not _is_valid("DraftNewEventOutput", {**ok, "error": ERROR})
    assert not _is_valid("DraftNewEventOutput", {**ok, "draft": {}})
    assert not _is_valid("DraftNewEventOutput", {**ok, "validation_issues": [issue]})
    assert not _is_valid("DraftNewEventOutput", {**failed, "error": None})
    assert not _is_valid("DraftNewEventOutput", {**failed, "draft": PREVIEW})