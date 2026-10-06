from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_current_user
from app.main import app
from app.services.event_draft_service import draft_new_event


client = TestClient(app)


@pytest.fixture(autouse=True)
def authenticated_user():
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u1")
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _valid_payload(**overrides):
    payload = {
        "title": "Spring Hackathon 2026",
        "description": "Collaborative 24-hour coding sprint.",
        "category": "tech",
        "cost": 15.0,
        "max_capacity": 100,
        "start_datetime": "2026-11-20T09:00:00+00:00",
        "end_datetime": "2026-11-20T21:00:00+00:00",
        "location_name": "Berlin Innovation Center",
        "latitude": 52.5200,
        "longitude": 13.4050,
    }
    payload.update(overrides)
    return payload


def _post(payload):
    return client.post(
        "/api/assistant/tools/draft-event",
        json=payload,
        headers={"Authorization": "Bearer test-token"},
    )


# ==========================================
# 1. Authentication & Contract Validation
# ==========================================

def test_draft_event_requires_authentication():
    app.dependency_overrides.pop(get_current_user, None)
    try:
        response = _post(_valid_payload())
        assert response.status_code in (401, 403)
    finally:
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u1")


def test_valid_input_returns_normalized_preview():
    payload = _valid_payload(
        title="  Clean Code Summit  ",
        description="  Best practices for architecture.  ",
        category="  technology  ",
    )
    response = _post(payload)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["error"] is None
    assert body["validation_issues"] == []
    UUID(body["request_id"])

    draft = body["draft"]
    assert draft["title"] == "Clean Code Summit"
    assert draft["description"] == "Best practices for architecture."
    assert draft["category"] == "technology"
    assert draft["cost"] == 15.0
    assert draft["max_capacity"] == 100
    assert draft["start_datetime"] == "2026-11-20T09:00:00+00:00"
    assert draft["end_datetime"] == "2026-11-20T21:00:00+00:00"
    assert draft["location_name"] == "Berlin Innovation Center"
    assert draft["latitude"] == 52.5200
    assert draft["longitude"] == 13.4050


# ==========================================
# 2. Field-Specific Validation Issues
# ==========================================

def test_missing_required_fields_returns_validation_issues():
    response = _post({})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["draft"] is None
    assert body["error"]["code"] == "INVALID_INPUT"

    issue_fields = [iss["field"] for iss in body["validation_issues"]]
    assert "title" in issue_fields
    assert "start_datetime" in issue_fields
    assert "end_datetime" in issue_fields


def test_date_order_violation_returns_error():
    # End datetime earlier than start datetime
    payload = _valid_payload(
        start_datetime="2026-11-20T20:00:00Z",
        end_datetime="2026-11-20T10:00:00Z",
    )
    response = _post(payload)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["draft"] is None

    date_issues = [iss for iss in body["validation_issues"] if iss.get("code") == "INVALID_DATE_ORDER"]
    assert len(date_issues) == 1
    assert date_issues[0]["field"] == "end_datetime"


def test_invalid_cost_and_capacity_returns_issues():
    payload = _valid_payload(cost=-5.0, max_capacity=0)
    response = _post(payload)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False

    issue_fields = [iss["field"] for iss in body["validation_issues"]]
    assert "cost" in issue_fields
    assert "max_capacity" in issue_fields


def test_invalid_geographic_coordinates_returns_issues():
    payload = _valid_payload(latitude=95.0, longitude=-190.0)
    response = _post(payload)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False

    issue_fields = [iss["field"] for iss in body["validation_issues"]]
    assert "latitude" in issue_fields
    assert "longitude" in issue_fields


def test_extra_unknown_fields_rejected():
    payload = _valid_payload(unknown_injected_field="malicious")
    response = _post(payload)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "INVALID_INPUT"
    assert "unknown_injected_field" in body["error"]["message"]


# ==========================================
# 3. Isolation & No Side-Effects Proof
# ==========================================

def test_preview_flow_does_not_persist_or_write_to_database():
    with patch("app.db.supabase_client.supabase") as mock_supabase:
        mock_supabase.table.side_effect = AssertionError("Draft preview must never touch Supabase tables!")
        
        response = _post(_valid_payload())

    assert response.status_code == 200
    assert response.json()["success"] is True
    mock_supabase.table.assert_not_called()


def test_preview_flow_does_not_call_ai_models_or_embeddings():
    with patch("app.services.assistant_service.OpenAI") as mock_openai, \
         patch("app.utils.embedding_helper.generate_embedding", side_effect=AssertionError("No embedding calls allowed!")):
        
        mock_openai.side_effect = AssertionError("Draft preview must make no AI model calls!")
        
        response = _post(_valid_payload())

    assert response.status_code == 200
    assert response.json()["success"] is True
    mock_openai.assert_not_called()
