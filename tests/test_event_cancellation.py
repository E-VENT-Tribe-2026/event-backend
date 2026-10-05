import pytest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.core.dependencies import get_current_onboarded_user
from tests._supabase_mock import make_table_router

client = TestClient(app)


class TestTicket145CancelEventsIntegration:
    """End-to-end route tests verifying all acceptance criteria for Ticket #145."""

    # 1. DELETE /api/events/{event_id} is refused
    def test_delete_event_is_refused(self):
        app.dependency_overrides[get_current_onboarded_user] = lambda: SimpleNamespace(id="u1")
        try:
            response = client.delete("/api/events/e1")
            assert response.status_code == 400
            assert "cannot be deleted" in response.json()["detail"].lower()
        finally:
            app.dependency_overrides.pop(get_current_onboarded_user, None)

    # 2. Cancel event authorization & conditions
    @patch("app.services.event_service.get_event")
    def test_cancel_non_organizer_refused(self, mock_get_event):
        mock_get_event.return_value = {
            "id": "e1",
            "created_by": "org1",
            "status": "active",
            "start_datetime": "2999-01-01T10:00:00+00:00"
        }
        app.dependency_overrides[get_current_onboarded_user] = lambda: SimpleNamespace(id="u2")
        try:
            response = client.patch("/api/events/e1/cancel")
            assert response.status_code == 403
        finally:
            app.dependency_overrides.pop(get_current_onboarded_user, None)

    @patch("app.services.event_service.get_event")
    def test_cancel_past_event_refused(self, mock_get_event):
        mock_get_event.return_value = {
            "id": "e1",
            "created_by": "org1",
            "status": "active",
            "start_datetime": "2020-01-01T10:00:00+00:00"
        }
        app.dependency_overrides[get_current_onboarded_user] = lambda: SimpleNamespace(id="org1")
        try:
            response = client.patch("/api/events/e1/cancel")
            assert response.status_code == 400
            assert "upcoming" in response.json()["detail"].lower()
        finally:
            app.dependency_overrides.pop(get_current_onboarded_user, None)

    @patch("app.services.event_service.get_event")
    def test_cancel_already_cancelled_refused(self, mock_get_event):
        mock_get_event.return_value = {
            "id": "e1",
            "created_by": "org1",
            "status": "cancelled",
            "start_datetime": "2999-01-01T10:00:00+00:00"
        }
        app.dependency_overrides[get_current_onboarded_user] = lambda: SimpleNamespace(id="org1")
        try:
            response = client.patch("/api/events/e1/cancel")
            assert response.status_code == 400
            assert "already cancelled" in response.json()["detail"].lower()
        finally:
            app.dependency_overrides.pop(get_current_onboarded_user, None)

    @patch("app.services.event_service._email_participants")
    @patch("app.services.notification_service.create_notification")
    @patch("app.services.event_service.get_username", return_value="alice")
    @patch("app.services.event_service.supabase")
    @patch("app.services.event_service.get_event")
    def test_cancel_upcoming_by_organizer_succeeds_both_patch_and_post(
        self, mock_get_event, mock_sb, mock_username, mock_notify, mock_email
    ):
        mock_get_event.return_value = {
            "id": "e1",
            "title": "Hackathon 2026",
            "created_by": "org1",
            "status": "active",
            "start_datetime": "2999-01-01T10:00:00+00:00"
        }
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.update.return_value = chain
        chain.delete.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[{"user_id": "p1"}])

        app.dependency_overrides[get_current_onboarded_user] = lambda: SimpleNamespace(id="org1")
        try:
            # Test PATCH
            resp_patch = client.patch("/api/events/e1/cancel")
            assert resp_patch.status_code == 200
            assert resp_patch.json() == {"message": "Event cancelled"}

            # Test POST
            resp_post = client.post("/api/events/e1/cancel")
            assert resp_post.status_code == 200
            assert resp_post.json() == {"message": "Event cancelled"}

            # Participants must NOT be deleted
            chain.delete.assert_not_called()
        finally:
            app.dependency_overrides.pop(get_current_onboarded_user, None)

    # 3. PUT /api/events/{event_id} on cancelled event is refused
    @patch("app.services.event_service.get_event")
    def test_update_cancelled_event_refused(self, mock_get_event):
        mock_get_event.return_value = {
            "id": "e1",
            "created_by": "org1",
            "status": "cancelled",
        }
        app.dependency_overrides[get_current_onboarded_user] = lambda: SimpleNamespace(id="org1")
        try:
            response = client.put("/api/events/e1", json={"title": "Revived Title"})
            assert response.status_code == 400
            assert "cannot edit a cancelled event" in response.json()["detail"].lower()
        finally:
            app.dependency_overrides.pop(get_current_onboarded_user, None)

    # 4. Refuse participant actions on cancelled event
    @patch("app.services.participant_service.get_event")
    def test_participant_operations_refused_on_cancelled_event(self, mock_get_event):
        mock_get_event.return_value = {
            "id": "e1",
            "created_by": "org1",
            "status": "cancelled",
        }
        app.dependency_overrides[get_current_onboarded_user] = lambda: SimpleNamespace(id="p1")
        try:
            # Join refused
            resp_join = client.post("/api/participants/e1/join")
            assert resp_join.status_code == 400
            assert "cannot join a cancelled event" in resp_join.json()["detail"].lower()

            # Leave refused
            resp_leave = client.post("/api/participants/e1/leave")
            assert resp_leave.status_code == 400
            assert "cannot leave a cancelled event" in resp_leave.json()["detail"].lower()

            # Remove participant refused
            app.dependency_overrides[get_current_onboarded_user] = lambda: SimpleNamespace(id="org1")
            resp_remove = client.delete("/api/participants/e1/participants/p1")
            assert resp_remove.status_code == 400
            assert "cannot remove participants from a cancelled event" in resp_remove.json()["detail"].lower()
        finally:
            app.dependency_overrides.pop(get_current_onboarded_user, None)

    # 5. Chat restrictions on cancelled event
    def test_chat_write_operations_refused_on_cancelled_event(self):
        mock_sb, chains = make_table_router()
        chains["event_participants"].execute.return_value = MagicMock(data=[{"user_id": "p1"}])
        chains["events"].execute.return_value = MagicMock(data={"status": "cancelled", "created_by": "org1"})
        chains["event_chats"].execute.return_value = MagicMock(
            data={"id": 10, "event_id": "e1", "sender_id": "p1", "content": "hello"}
        )

        app.dependency_overrides[get_current_onboarded_user] = lambda: SimpleNamespace(id="p1")
        try:
            with patch("app.services.chat_service.supabase", mock_sb):
                # Send refused
                resp_send = client.post("/api/chats/e1/messages", json={"content": "New message"})
                assert resp_send.status_code == 400
                assert "read-only" in resp_send.json()["detail"].lower()

                # Edit refused
                resp_edit = client.put("/api/chats/messages/10", json={"content": "Edited message"})
                assert resp_edit.status_code == 400
                assert "read-only" in resp_edit.json()["detail"].lower()

                # Delete refused
                resp_del = client.delete("/api/chats/messages/10")
                assert resp_del.status_code == 400
                assert "read-only" in resp_del.json()["detail"].lower()
        finally:
            app.dependency_overrides.pop(get_current_onboarded_user, None)
