import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.core.dependencies import get_current_user
from tests._supabase_mock import make_table_router


# ────────────────────────────────────────────────────────────────────────────
# Regression guards: participant list / participant count / chat messages
# routes must stay behind auth (never treated as public paths).
# ────────────────────────────────────────────────────────────────────────────

class TestPublicPathsRegression:
    def test_participants_route_is_not_public(self):
        from app.core.jwt_middleware import _is_public
        assert _is_public("/api/participants/e1/participants") is False

    def test_participants_count_route_is_not_public(self):
        from app.core.jwt_middleware import _is_public
        assert _is_public("/api/participants/e1/participants/count") is False

    def test_chat_messages_route_is_not_public(self):
        from app.core.jwt_middleware import _is_public
        assert _is_public("/api/chats/e1/messages") is False


# ────────────────────────────────────────────────────────────────────────────
# Schemas: UserSummary shape and ChatMessageResponse.sender
# ────────────────────────────────────────────────────────────────────────────

class TestUserSummarySchemas:
    def test_user_summary_has_exact_fields_and_icon_default(self):
        from app.schemas.profile_schema import UserSummary
        dumped = UserSummary(id="u1").model_dump()
        assert set(dumped.keys()) == {
            "id", "username", "full_name", "display_name",
            "avatar_kind", "icon_id", "avatar_url",
        }
        assert dumped["avatar_kind"] == "icon"

    def test_chat_message_response_keeps_sender_and_accepts_none(self):
        from app.schemas.chat_schema import ChatMessageResponse
        base = {"id": 1, "event_id": "e1", "content": "hi", "created_at": "2026-04-22T16:00:00Z"}
        sender = {
            "id": "u1", "username": "john_42", "full_name": "John Doe", "display_name": "john_42",
            "avatar_kind": "icon", "icon_id": "icon_fox", "avatar_url": None,
        }

        with_sender = ChatMessageResponse(**base, sender_id="u1", sender=sender).model_dump()
        assert with_sender["sender"]["username"] == "john_42"
        assert with_sender["sender"]["icon_id"] == "icon_fox"

        system = ChatMessageResponse(**base, sender_id=None, sender_name="System",
                                     sender_role="system", sender=None).model_dump()
        assert system["sender"] is None
        assert system["sender_name"] == "System"


# ────────────────────────────────────────────────────────────────────────────
# Route-level check: nested `sender` summary must survive the response_model
# ────────────────────────────────────────────────────────────────────────────

client = TestClient(app)


class TestChatSendMessageRouteIncludesSender:
    @patch("app.api.v1.chat_routes.send_message")
    def test_post_message_response_includes_nested_sender(self, mock_send):
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u1")
        try:
            mock_send.return_value = {
                "id": 1,
                "event_id": "e1",
                "sender_id": "u1",
                "sender_name": "John Doe",
                "sender_role": "participant",
                "content": "hello",
                "created_at": "2026-04-22T16:00:00Z",
                "sender": {
                    "id": "u1",
                    "username": "john_42",
                    "full_name": "John Doe",
                    "display_name": "john_42",
                    "avatar_kind": "icon",
                    "icon_id": "icon_fox",
                    "avatar_url": None,
                },
            }

            response = client.post(
                "/api/chats/e1/messages",
                json={"content": "hello"},
                headers={"Authorization": "Bearer token"},
            )

            assert response.status_code == 201
            data = response.json()
            assert data["sender"]["username"] == "john_42"
            assert data["sender"]["icon_id"] == "icon_fox"
        finally:
            app.dependency_overrides.pop(get_current_user, None)


# ────────────────────────────────────────────────────────────────────────────
# Route-level check: PUT /messages/{id} runs the real update_message path
# ────────────────────────────────────────────────────────────────────────────

class TestChatUpdateMessageRouteRealPath:
    def test_put_message_response_includes_nested_sender_and_role(self):
        mock_sb, chains = make_table_router()
        chains["event_chats"].execute.side_effect = [
            MagicMock(data={"id": 1, "event_id": "e1", "sender_id": "u1", "content": "old"}),
            MagicMock(data=[{
                "id": 1, "event_id": "e1", "sender_id": "u1", "content": "new",
                "created_at": "2026-04-22T16:00:00Z",
            }]),
        ]
        chains["events"].execute.return_value = MagicMock(data={"created_by": "someone_else"})

        summary = {
            "id": "u1", "username": "john_42", "full_name": "John Doe", "display_name": "john_42",
            "avatar_kind": "icon", "icon_id": "icon_fox", "avatar_url": None,
        }

        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u1")
        try:
            with patch("app.services.chat_service.supabase", mock_sb), \
                 patch("app.services.chat_service.get_user_summaries", return_value={"u1": summary}):
                response = client.put(
                    "/api/chats/messages/1",
                    json={"content": "new"},
                    headers={"Authorization": "Bearer token"},
                )

            assert response.status_code == 200
            data = response.json()
            assert data["sender"]["username"] == "john_42"
            assert data["sender"]["icon_id"] == "icon_fox"
            assert data["sender_name"] == "John Doe"
            assert data["sender_role"] == "participant"
            assert data["content"] == "new"
        finally:
            app.dependency_overrides.pop(get_current_user, None)


# ────────────────────────────────────────────────────────────────────────────
# Route-level check: GET /participants runs the real get_event_participants path
# ────────────────────────────────────────────────────────────────────────────

class TestParticipantsRouteRealPath:
    def test_get_participants_response_includes_user_summary_and_profiles(self):
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[
            {
                "user_id": "u1",
                "status": "going",
                "profiles": {
                    "username": "jill5",
                    "full_name": "Jill Five",
                    "avatar_url": "https://cdn.example.com/j.png",
                    "avatar_kind": "icon",
                    "icon_id": "icon_fox",
                },
            },
            {
                "user_id": "u2",
                "status": "going",
                "profiles": None,
            },
        ])
        mock_sb = MagicMock()
        mock_sb.table.return_value = chain

        with patch("app.services.participant_service.supabase", mock_sb):
            response = client.get("/api/participants/e1/participants")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

        expected_keys = {"id", "username", "full_name", "display_name", "avatar_kind", "icon_id", "avatar_url"}
        for item in data:
            assert set(item["user"].keys()) == expected_keys

        first, second = data
        assert first["profiles"] == {"full_name": "Jill Five", "avatar_url": "https://cdn.example.com/j.png"}
        assert first["user"]["icon_id"] == "icon_fox"

        assert second["profiles"] is None
        assert second["user"]["id"] == second["user_id"]

    def test_get_participants_list_shaped_embed_with_none_yields_stub_user(self):
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[
            {
                "user_id": "u3",
                "status": "going",
                "profiles": [None],
            }
        ])
        mock_sb = MagicMock()
        mock_sb.table.return_value = chain

        with patch("app.services.participant_service.supabase", mock_sb):
            response = client.get("/api/participants/e1/participants")

        assert response.status_code == 200
        data = response.json()
        item = data[0]
        assert item["user"]["id"] == "u3"
        assert item["profiles"] is None


# ────────────────────────────────────────────────────────────────────────────
# Route-level check: GET /messages runs the real get_event_messages path
# ────────────────────────────────────────────────────────────────────────────

class TestChatMessagesRouteRealPath:
    def test_get_messages_response_includes_sender_and_system_message(self):
        mock_sb, chains = make_table_router()
        chains["event_participants"].execute.return_value = MagicMock(data=[{"user_id": "u1"}])
        chains["event_chats"].execute.return_value = MagicMock(data=[
            {
                "id": 1, "event_id": "e1", "sender_id": "u1", "content": "hi",
                "type": "chat", "created_at": "2026-04-22T16:00:00Z",
            },
            {
                "id": 2, "event_id": "e1", "sender_id": None, "content": "joined",
                "type": "notification", "created_at": "2026-04-22T16:01:00Z",
            },
        ])
        chains["events"].execute.return_value = MagicMock(data={"created_by": "u1"})

        summary = {
            "id": "u1", "username": "john_42", "full_name": "John Doe", "display_name": "john_42",
            "avatar_kind": "icon", "icon_id": "icon_fox", "avatar_url": None,
        }

        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u1")
        try:
            with patch("app.services.chat_service.supabase", mock_sb), \
                 patch("app.services.chat_service.get_user_summaries", return_value={"u1": summary}):
                response = client.get(
                    "/api/chats/e1/messages",
                    headers={"Authorization": "Bearer token"},
                )

            assert response.status_code == 200
            data = response.json()["data"]

            user_msg = next(m for m in data if m["id"] == 1)
            system_msg = next(m for m in data if m["id"] == 2)

            assert user_msg["sender"]["username"] == "john_42"
            assert user_msg["sender_role"] == "organizer"

            assert system_msg["sender"] is None
            assert system_msg["sender_name"] == "System"
            assert system_msg["sender_role"] == "system"
        finally:
            app.dependency_overrides.pop(get_current_user, None)
