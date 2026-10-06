from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_current_user
from app.main import app
from app.services import event_search_service


client = TestClient(app)


@pytest.fixture(autouse=True)
def authenticated_user():
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u1")
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _row(**overrides):
    row = {
        "id": "11111111-1111-1111-1111-111111111111",
        "title": "Jazz Night",
        "description": "Live jazz",
        "category": "music",
        "cost": 12,
        "max_capacity": 40,
        "status": "active",
        "start_datetime": "2026-06-15T18:00:00+00:00",
        "end_datetime": "2026-06-15T21:00:00+00:00",
        "location_name": "Berlin Hall",
    }
    row.update(overrides)
    return row


def _stub_query(rows, total):
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.gte.return_value = chain
    chain.gt.return_value = chain
    chain.lt.return_value = chain
    chain.ilike.return_value = chain
    chain.or_.return_value = chain
    chain.order.return_value = chain
    chain.range.return_value = chain
    chain.execute.return_value = MagicMock(data=rows, count=total)
    supabase = MagicMock()
    supabase.table.return_value = chain
    return supabase, chain


def _post(payload):
    return client.post(
        "/api/assistant/tools/search-events",
        json=payload,
        headers={"Authorization": "Bearer test-token"},
    )


def test_search_requires_authentication():
    app.dependency_overrides.pop(get_current_user, None)
    try:
        response = _post({})
        assert response.status_code in (401, 403)
    finally:
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u1")


def test_combined_filters_pagination_and_ordering():
    supabase, chain = _stub_query([_row()], total=25)
    with patch("app.services.event_search_service.supabase", supabase):
        response = _post(
            {
                "query": "jazz",
                "category": "music",
                "upcoming": True,
                "date": "2026-06-15",
                "city": "Berlin",
                "page": 2,
                "limit": 10,
            }
        )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["error"] is None
    UUID(body["request_id"])
    assert body["events"] == [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "title": "Jazz Night",
            "description": "Live jazz",
            "category": "music",
            "start_datetime": "2026-06-15T18:00:00+00:00",
            "end_datetime": "2026-06-15T21:00:00+00:00",
            "location_name": "Berlin Hall",
            "cost": 12.0,
            "max_capacity": 40,
            "status": "active",
        }
    ]
    assert body["pagination"] == {"page": 2, "limit": 10, "total": 25, "has_next": True}

    supabase.table.assert_called_once_with("events")
    chain.select.assert_called_once()
    assert chain.select.call_args.kwargs["count"] == "exact"
    chain.eq.assert_any_call("status", "active")
    chain.eq.assert_any_call("category", "music")
    assert chain.gte.call_args_list[0].args[0] == "end_datetime"
    chain.gt.assert_called_once()
    assert chain.gt.call_args.args[0] == "start_datetime"
    chain.gte.assert_any_call("start_datetime", "2026-06-15T00:00:00+00:00")
    chain.lt.assert_called_once_with("start_datetime", "2026-06-16T00:00:00+00:00")
    chain.ilike.assert_called_once_with("location_name", "%Berlin%")
    chain.or_.assert_called_once_with('title.ilike."%jazz%",description.ilike."%jazz%"')
    assert [call.args for call in chain.order.call_args_list] == [
        ("start_datetime",),
        ("id",),
    ]
    assert [call.kwargs["desc"] for call in chain.order.call_args_list] == [False, False]
    chain.range.assert_called_once_with(10, 19)


def test_filters_can_be_omitted_and_upcoming_defaults_to_true():
    supabase, chain = _stub_query([_row()], total=1)
    with patch("app.services.event_search_service.supabase", supabase):
        response = _post({})

    assert response.status_code == 200
    assert response.json()["success"] is True
    chain.gt.assert_called_once()
    chain.ilike.assert_not_called()
    chain.or_.assert_not_called()
    chain.eq.assert_any_call("status", "active")


def test_upcoming_false_skips_future_start_filter():
    supabase, chain = _stub_query([], total=0)
    with patch("app.services.event_search_service.supabase", supabase):
        response = _post({"upcoming": False})

    assert response.status_code == 200
    chain.gt.assert_not_called()
    chain.gte.assert_called_once()
    assert chain.gte.call_args.args[0] == "end_datetime"


def test_empty_search_is_successful():
    supabase, _chain = _stub_query([], total=0)
    with patch("app.services.event_search_service.supabase", supabase):
        response = _post({"query": "   ", "city": ""})

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["events"] == []
    assert response.json()["pagination"] == {
        "page": 1,
        "limit": 10,
        "total": 0,
        "has_next": False,
    }
    assert response.json()["error"] is None


def test_last_page_has_no_next_page():
    supabase, chain = _stub_query([], total=25)
    with patch("app.services.event_search_service.supabase", supabase):
        response = _post({"page": 3, "limit": 10})

    assert response.json()["pagination"]["has_next"] is False
    chain.range.assert_called_once_with(20, 29)


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"page": 0}, "page"),
        ({"page": -1}, "page"),
        ({"limit": 0}, "limit"),
        ({"limit": 51}, "limit"),
        ({"date": "15-06-2026"}, "date"),
        ({"date": "2026-02-31"}, "date"),
        ({"query": "x" * 201}, "query"),
        ({"category": "x" * 101}, "category"),
        ({"city": "x" * 121}, "city"),
        ({"upcoming": "yes"}, "upcoming"),
        ({"page": 1.5}, "page"),
        ({"tools": []}, "tools"),
        (["jazz"], None),
    ],
)
def test_invalid_input_returns_structured_error_without_querying(payload, field):
    supabase, _chain = _stub_query([], total=0)
    with patch("app.services.event_search_service.supabase", supabase):
        response = _post(payload)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["events"] == []
    assert body["error"]["code"] == "INVALID_INPUT"
    assert body["error"]["field"] == field
    assert body["error"]["message"]
    supabase.table.assert_not_called()


def test_text_wildcards_are_escaped():
    supabase, chain = _stub_query([], total=0)
    with patch("app.services.event_search_service.supabase", supabase):
        response = _post({"query": "100%_jazz", "city": "100%_Berlin"})

    assert response.status_code == 200
    chain.ilike.assert_called_once_with("location_name", r"%100\%\_Berlin%")
    chain.or_.assert_called_once_with(
        r'title.ilike."%100\%\_jazz%",description.ilike."%100\%\_jazz%"'
    )


def test_database_failure_returns_safe_internal_error():
    supabase, chain = _stub_query([], total=0)
    chain.execute.side_effect = RuntimeError("relation events password=secret")
    with patch("app.services.event_search_service.supabase", supabase):
        response = _post({"query": "jazz"})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert body["error"]["message"] == "Event search is temporarily unavailable."
    assert "secret" not in response.text
    assert "relation" not in response.text


def test_search_does_not_call_a_chat_model_or_embedding_provider():
    supabase, _chain = _stub_query([_row()], total=1)
    with patch("app.services.event_search_service.supabase", supabase), patch(
        "app.utils.embedding_helper.generate_embedding",
        side_effect=AssertionError("embedding provider called"),
    ) as embedding, patch(
        "app.services.event_service.generate_embedding",
        side_effect=AssertionError("event embedding helper called"),
    ) as event_embedding, patch(
        "app.services.event_service.list_events",
        side_effect=AssertionError("semantic event list called"),
    ) as list_events, patch(
        "openai.OpenAI",
        side_effect=AssertionError("chat model called"),
    ) as openai_client:
        response = _post({"query": "jazz"})

    assert response.status_code == 200
    assert response.json()["success"] is True
    embedding.assert_not_called()
    event_embedding.assert_not_called()
    list_events.assert_not_called()
    openai_client.assert_not_called()

    source = open(event_search_service.__file__, encoding="utf-8").read().lower()
    assert "generate_embedding" not in source
    assert "openai" not in source
    assert "list_events" not in source
