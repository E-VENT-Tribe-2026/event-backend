from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_current_user
from app.main import app
from app.services.assistant_conversation_service import (
    list_history,
    record_exchange,
    start_conversation,
)
from tests._supabase_mock import make_table_router


client = TestClient(app)


@pytest.fixture
def authenticated_user():
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="user-a")
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _rows(data):
    result = MagicMock()
    result.data = data
    return result


def test_history_is_empty_when_the_user_has_no_conversation():
    mock_sb, chains = make_table_router()
    chains["ai_conversations"].execute.return_value = _rows([])
    with patch("app.services.assistant_conversation_service.supabase", mock_sb):
        history = list_history("user-a")

    assert history == {"conversation_id": None, "messages": []}
    chains["ai_conversations"].eq.assert_called_with("user_id", "user-a")
    chains["ai_messages"].select.assert_not_called()


def test_history_returns_only_the_signed_in_users_latest_conversation():
    mock_sb, chains = make_table_router()
    chains["ai_conversations"].execute.return_value = _rows([{"id": "conversation-1"}])
    chains["ai_messages"].execute.return_value = _rows(
        [
            {
                "id": "message-2",
                "role": "assistant",
                "content": "I found a concert.",
                "metadata": {"type": "event_search_results", "events": [{"id": "event-1", "title": "Concert"}]},
                "created_at": "2026-11-15T10:01:00+00:00",
            },
            {
                "id": "message-1",
                "role": "user",
                "content": "Find a concert",
                "metadata": {},
                "created_at": "2026-11-15T10:00:00+00:00",
            },
        ]
    )
    with patch("app.services.assistant_conversation_service.supabase", mock_sb):
        history = list_history("user-a")

    assert history["conversation_id"] == "conversation-1"
    assert [message["content"] for message in history["messages"]] == [
        "Find a concert",
        "I found a concert.",
    ]
    assert history["messages"][1]["metadata"]["events"][0]["title"] == "Concert"
    chains["ai_conversations"].eq.assert_called_with("user_id", "user-a")
    chains["ai_messages"].eq.assert_called_with("conversation_id", "conversation-1")


def test_history_keeps_each_question_before_its_reply_when_they_share_a_timestamp():
    same_time = "2026-11-15T10:00:00+00:00"
    later = "2026-11-15T10:05:00+00:00"
    mock_sb, chains = make_table_router()
    chains["ai_conversations"].execute.return_value = _rows([{"id": "conversation-1"}])
    chains["ai_messages"].execute.return_value = _rows(
        [
            {"id": "message-1", "role": "user", "content": "First question", "metadata": {}, "created_at": same_time},
            {"id": "message-2", "role": "assistant", "content": "First answer", "metadata": {}, "created_at": same_time},
            {"id": "message-4", "role": "assistant", "content": "Second answer", "metadata": {}, "created_at": later},
            {"id": "message-3", "role": "user", "content": "Second question", "metadata": {}, "created_at": later},
        ]
    )
    with patch("app.services.assistant_conversation_service.supabase", mock_sb):
        history = list_history("user-a")

    assert [message["content"] for message in history["messages"]] == [
        "First question",
        "First answer",
        "Second question",
        "Second answer",
    ]


def test_new_conversation_hides_the_previous_messages():
    mock_sb, chains = make_table_router()
    chains["ai_conversations"].execute.side_effect = [
        _rows([{"id": "conversation-1"}]),
        _rows([{"id": "conversation-2"}]),
    ]
    chains["ai_messages"].execute.return_value = _rows([{"id": "message-1"}])
    with patch("app.services.assistant_conversation_service.supabase", mock_sb):
        created = start_conversation("user-a")

    assert created == {"conversation_id": "conversation-2"}
    inserted = chains["ai_conversations"].insert.call_args.args[0]
    assert inserted["user_id"] == "user-a"
    assert inserted["title"] == "New chat"


def test_new_conversation_reuses_an_empty_latest_conversation():
    mock_sb, chains = make_table_router()
    chains["ai_conversations"].execute.side_effect = [
        _rows([{"id": "conversation-1"}]),
        _rows([{"id": "conversation-1"}]),
    ]
    chains["ai_messages"].execute.return_value = _rows([])
    with patch("app.services.assistant_conversation_service.supabase", mock_sb):
        created = start_conversation("user-a")

    assert created == {"conversation_id": "conversation-1"}
    chains["ai_conversations"].insert.assert_not_called()


def test_completed_turn_is_appended_to_the_active_conversation():
    mock_sb, chains = make_table_router()
    chains["ai_conversations"].execute.side_effect = [
        _rows([{"id": "conversation-1"}]),
        _rows([{"id": "conversation-1"}]),
    ]
    chains["ai_messages"].execute.return_value = _rows([])
    metadata = {
        "type": "draft_event_preview",
        "draft": {"title": "Jazz Night"},
        "validation_issues": ["Location required"],
    }
    with patch("app.services.assistant_conversation_service.supabase", mock_sb):
        record_exchange("user-a", "Draft a jazz night", "Here is the draft.", metadata)

    stored = chains["ai_messages"].insert.call_args.args[0]
    assert stored[0]["role"] == "user"
    assert stored[0]["content"] == "Draft a jazz night"
    assert stored[0]["conversation_id"] == "conversation-1"
    assert stored[0]["created_at"] < stored[1]["created_at"]
    assert stored[1]["role"] == "assistant"
    assert stored[1]["metadata"]["draft"]["title"] == "Jazz Night"
    assert stored[1]["metadata"]["validation_issues"] == ["Location required"]


def test_storage_failure_does_not_raise():
    mock_sb, chains = make_table_router()
    chains["ai_conversations"].execute.side_effect = RuntimeError("database down")
    with patch("app.services.assistant_conversation_service.supabase", mock_sb):
        record_exchange("user-a", "Hello", "Hi there.")


def test_history_route_uses_the_token_user_and_returns_an_empty_thread(authenticated_user):
    with patch(
        "app.api.v1.assistant_routes.list_history",
        return_value={"conversation_id": None, "messages": []},
    ) as listed:
        response = client.get(
            "/api/assistant/messages?user_id=someone-else",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    assert response.json() == {"conversation_id": None, "messages": []}
    listed.assert_called_once_with("user-a")


def test_history_route_requires_a_signed_in_user():
    app.dependency_overrides.pop(get_current_user, None)
    response = client.get("/api/assistant/messages")
    assert response.status_code in {401, 403}


def test_new_conversation_route_returns_the_new_session(authenticated_user):
    with patch(
        "app.api.v1.assistant_routes.start_conversation",
        return_value={"conversation_id": "conversation-2"},
    ) as started:
        response = client.post(
            "/api/assistant/conversations",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    assert response.json() == {"conversation_id": "conversation-2"}
    started.assert_called_once_with("user-a")
