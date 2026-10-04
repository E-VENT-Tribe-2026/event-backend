from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_current_user
from app.main import app
from app.services import event_details_service
from app.services.event_details_service import get_event_details


client = TestClient(app)
EVENT_ID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture(autouse=True)
def authenticated_user():
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u1")
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _row(**overrides):
    row = {
        "id": EVENT_ID,
        "title": "Jazz Night",
        "description": None,
        "category": "music",
        "cost": 12,
        "max_capacity": None,
        "status": "active",
        "start_datetime": "2027-06-15T18:00:00+00:00",
        "end_datetime": "2027-06-15T21:00:00+00:00",
        "location_name": "Berlin Hall",
        "latitude": 52.52,
        "longitude": None,
        "created_by": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    }
    row.update(overrides)
    return row


def _stub_lookup(rows):
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.limit.return_value = chain
    chain.execute.return_value = MagicMock(data=rows)
    supabase = MagicMock()
    supabase.table.return_value = chain
    return supabase, chain


def _post(payload):
    return client.post(
        "/api/assistant/tools/event-details",
        json=payload,
        headers={"Authorization": "Bearer test-token"},
    )


def test_event_details_requires_authentication():
    app.dependency_overrides.pop(get_current_user, None)
    try:
        response = _post({"event_id": EVENT_ID})
        assert response.status_code in (401, 403)
    finally:
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u1")


def test_successful_lookup_returns_current_details_and_null_optional_fields():
    supabase, chain = _stub_lookup([_row()])
    with patch("app.services.event_details_service.supabase", supabase):
        response = _post({"event_id": f"  {EVENT_ID}  "})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["error"] is None
    UUID(body["request_id"])
    assert body["event"] == {
        "id": EVENT_ID,
        "title": "Jazz Night",
        "description": None,
        "category": "music",
        "cost": 12.0,
        "max_capacity": None,
        "start_datetime": "2027-06-15T18:00:00+00:00",
        "end_datetime": "2027-06-15T21:00:00+00:00",
        "location_name": "Berlin Hall",
        "latitude": 52.52,
        "longitude": None,
        "created_by": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "status": "active",
    }
    supabase.table.assert_called_once_with("events")
    selected = chain.select.call_args.args[0]
    assert "event_embedding" not in selected
    chain.eq.assert_called_once_with("id", EVENT_ID)


def test_missing_event_returns_not_found():
    supabase, _chain = _stub_lookup([])
    missing_id = str(uuid4())
    with patch("app.services.event_details_service.supabase", supabase):
        response = _post({"event_id": missing_id})

    body = response.json()
    assert response.status_code == 200
    assert body["success"] is False
    assert body["event"] is None
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["field"] == "event_id"


@pytest.mark.parametrize(
    ("row",),
    [
        (_row(status="cancelled"),),
        (_row(end_datetime="2020-01-01T00:00:00+00:00"),),
    ],
)
def test_existing_event_outside_the_catalog_is_access_denied(row):
    supabase, _chain = _stub_lookup([row])
    with patch("app.services.event_details_service.supabase", supabase):
        response = _post({"event_id": EVENT_ID})

    body = response.json()
    assert response.status_code == 200
    assert body["success"] is False
    assert body["event"] is None
    assert body["error"] == {
        "code": "FORBIDDEN",
        "message": "You cannot view this event.",
        "field": None,
    }


@pytest.mark.parametrize(
    ("payload", "field", "message"),
    [
        ({}, "event_id", "Event ID is required."),
        ({"event_id": "   "}, "event_id", "Event ID is required."),
        ({"event_id": "not-a-uuid"}, "event_id", "Event ID must be a UUID."),
        ({"event_id": 12}, "event_id", "Event ID must be a UUID."),
        ({"event_id": EVENT_ID, "user_id": "someone-else"}, "user_id", "Unknown field."),
        (["nope"], None, "Event details input must be an object."),
    ],
)
def test_invalid_id_returns_structured_error_without_querying(payload, field, message):
    supabase, _chain = _stub_lookup([_row()])
    with patch("app.services.event_details_service.supabase", supabase):
        response = _post(payload)

    body = response.json()
    assert response.status_code == 200
    assert body["success"] is False
    assert body["event"] is None
    assert body["error"]["code"] == "INVALID_INPUT"
    assert body["error"]["field"] == field
    assert body["error"]["message"] == message
    supabase.table.assert_not_called()


def test_missing_user_is_rejected_before_lookup():
    supabase, _chain = _stub_lookup([_row()])
    with patch("app.services.event_details_service.supabase", supabase):
        body = get_event_details({"event_id": EVENT_ID}, None)

    assert body["success"] is False
    assert body["error"]["code"] == "UNAUTHORIZED"
    supabase.table.assert_not_called()


def test_database_failure_returns_safe_internal_error():
    supabase, chain = _stub_lookup([])
    chain.execute.side_effect = RuntimeError("relation events password=secret")
    with patch("app.services.event_details_service.supabase", supabase):
        response = _post({"event_id": EVENT_ID})

    assert response.status_code == 200
    assert "secret" not in response.text
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert response.json()["error"]["message"] == "Event details are temporarily unavailable."


def test_event_details_does_not_call_a_chat_model_or_embedding_provider():
    supabase, _chain = _stub_lookup([_row()])
    with patch("app.services.event_details_service.supabase", supabase), patch(
        "app.utils.embedding_helper.generate_embedding",
        side_effect=AssertionError("embedding provider called"),
    ) as embedding, patch(
        "app.services.event_service.generate_embedding",
        side_effect=AssertionError("event embedding helper called"),
    ) as event_embedding, patch(
        "app.services.event_service.get_event",
        side_effect=AssertionError("public event lookup called"),
    ) as get_event, patch(
        "openai.OpenAI",
        side_effect=AssertionError("chat model called"),
    ) as openai_client:
        response = _post({"event_id": EVENT_ID})

    assert response.status_code == 200
    assert response.json()["success"] is True
    embedding.assert_not_called()
    event_embedding.assert_not_called()
    get_event.assert_not_called()
    openai_client.assert_not_called()

    source = open(event_details_service.__file__, encoding="utf-8").read().lower()
    assert "generate_embedding" not in source
    assert "openai" not in source
    assert "event_service" not in source
