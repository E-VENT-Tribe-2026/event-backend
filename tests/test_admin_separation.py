import base64
import json
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.core.dependencies import get_current_user, require_admin, require_regular_user, get_current_onboarded_user

client = TestClient(app)


def _create_jwt(payload: dict) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).decode().rstrip("=")
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{header}.{body}.sig"


class MockRegularUser:
    id = "11111111-1111-1111-1111-111111111111"
    email = "user@example.com"


class MockAdminUser:
    id = "22222222-2222-2222-2222-222222222222"
    email = "admin@example.com"


class TestAdminSeparation:
    """
    Test suite covering Sprint 3 Ticket:
    Separating Administrator accounts from User accounts.
    """

    # 1. Administrators do not appear in profile search
    @patch("app.services.profile_service.supabase")
    def test_search_profiles_excludes_administrators(self, mock_sb):
        app.dependency_overrides[require_regular_user] = lambda: MockRegularUser()
        try:
            chain = MagicMock()
            chain.select.return_value = chain
            chain.in_.return_value = chain
            chain.ilike.return_value = chain
            chain.neq.return_value = chain
            chain.is_.return_value = chain
            chain.order.return_value = chain
            chain.range.return_value = chain
            chain.execute.return_value = MagicMock(data=[
                {
                    "id": "regular-user-id",
                    "full_name": "Alice Regular",
                    "avatar_url": None,
                    "avatar_kind": "icon",
                    "icon_id": "1",
                    "bio": "Bio",
                    "visibility": "public",
                    "username": "alice",
                    "role": "user"
                }
            ])
            mock_sb.table.return_value = chain

            res = client.get("/api/profile/search?q=ali")
            assert res.status_code == 200
            data = res.json()["data"]
            assert len(data) == 1
            assert data[0]["username"] == "alice"
            assert data[0]["role"] == "user"
            # Verify neq was called with administrator and admin
            neq_calls = [call.args for call in chain.neq.call_args_list]
            assert ("role", "administrator") in neq_calls
            assert ("role", "admin") in neq_calls
        finally:
            app.dependency_overrides.pop(require_regular_user, None)

    # 2. Another user's request for an administrator's profile answers that profile is unavailable (404)
    @patch("app.services.public_profile_service.get_public_profile")
    def test_view_administrator_profile_returns_unavailable(self, mock_get_profile):
        app.dependency_overrides[require_regular_user] = lambda: MockRegularUser()
        try:
            mock_get_profile.return_value = {
                "id": "admin-target-id",
                "username": "admin_person",
                "full_name": "Admin Person",
                "role": "administrator",
                "visibility": "public",
            }
            res = client.get("/api/profile/00000000-0000-0000-0000-000000000001")
            assert res.status_code == 404
            err = res.json()["detail"]
            assert err["code"] == "profile_unavailable"
            assert "unavailable" in err["message"].lower()
        finally:
            app.dependency_overrides.pop(require_regular_user, None)

    # 3. Friend request to an administrator is refused
    @patch("app.services.friendship_service.supabase")
    def test_send_friend_request_to_administrator_refused(self, mock_sb):
        app.dependency_overrides[require_regular_user] = lambda: MockRegularUser()
        app.dependency_overrides[get_current_onboarded_user] = lambda: MockRegularUser()
        try:
            chain = MagicMock()
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.limit.return_value = chain
            chain.execute.return_value = MagicMock(data=[
                {"id": "admin-target-id", "role": "administrator"}
            ])
            mock_sb.table.return_value = chain

            res = client.post("/api/friends/requests", json={"receiver_id": "00000000-0000-0000-0000-000000000001"})
            assert res.status_code == 404
            assert "user_not_found" in str(res.json())
        finally:
            app.dependency_overrides.pop(require_regular_user, None)
            app.dependency_overrides.pop(get_current_onboarded_user, None)

    # 4. Past events organized by former users still show them as organizer (full name & picture, without username)
    @patch("app.services.profile_service.supabase")
    def test_past_event_organizer_shows_full_name_and_picture_without_username(self, mock_sb):
        from app.services.profile_service import build_user_summary

        # Administrator profile
        admin_profile = {
            "id": "admin-past-org",
            "username": "former_super_user",
            "full_name": "Super Former",
            "avatar_url": "https://img.com/avatar.png",
            "avatar_kind": "photo",
            "icon_id": None,
            "role": "administrator"
        }

        summary = build_user_summary(admin_profile)
        assert summary["username"] is None
        assert summary["full_name"] == "Super Former"
        assert summary["display_name"] == "Super Former"
        assert summary["avatar_url"] == "https://img.com/avatar.png"

    # 5. An account without a username can be made an administrator
    @patch("app.services.admin_service.supabase")
    def test_account_without_username_can_be_made_admin(self, mock_sb):
        app.dependency_overrides[require_admin] = lambda: MockAdminUser()
        try:
            def table_router(table_name):
                chain = MagicMock()
                chain.select.return_value = chain
                chain.eq.return_value = chain
                chain.neq.return_value = chain
                chain.single.return_value = chain
                chain.update.return_value = chain
                chain.delete.return_value = chain
                chain.insert.return_value = chain

                if table_name == "profiles":
                    chain.execute.return_value = MagicMock(data=[{
                        "id": "user-no-username",
                        "username": None,
                        "full_name": "No Username User",
                        "role": "user"
                    }])
                elif table_name == "events":
                    chain.execute.return_value = MagicMock(data=[])
                elif table_name == "event_participants":
                    chain.execute.return_value = MagicMock(data=[])
                else:
                    chain.execute.return_value = MagicMock(data=[])
                return chain

            mock_sb.table.side_effect = table_router

            res = client.post("/api/admin/users/user-no-username/grant-admin")
            assert res.status_code == 200
            data = res.json()
            assert data["role"] == "administrator"
            assert data["user_id"] == "user-no-username"
            assert "admin_since" in data
        finally:
            app.dependency_overrides.pop(require_admin, None)

    # 6. Making a user an administrator cancels upcoming events with reason and sends notifications
    @patch("app.services.notification_service.create_notification")
    @patch("app.services.admin_service.supabase")
    def test_making_user_admin_cancels_events_and_notifies_participants(self, mock_sb, mock_notify):
        app.dependency_overrides[require_admin] = lambda: MockAdminUser()
        try:
            now = datetime.now(timezone.utc)
            future_iso = (now + timedelta(days=3)).isoformat()
            past_iso = (now - timedelta(days=3)).isoformat()

            events_updated = []
            deleted_tables = []

            def table_router(table_name):
                chain = MagicMock()
                chain.select.return_value = chain
                chain.eq.return_value = chain
                chain.neq.return_value = chain
                chain.single.return_value = chain
                chain.in_.return_value = chain

                def update_side_effect(payload):
                    events_updated.append((table_name, payload))
                    chain.execute.return_value = MagicMock(data=[payload])
                    return chain
                chain.update.side_effect = update_side_effect

                def delete_side_effect():
                    deleted_tables.append(table_name)
                    return chain
                chain.delete.side_effect = delete_side_effect

                if table_name == "profiles":
                    chain.execute.return_value = MagicMock(data=[{
                        "id": "u-to-admin",
                        "username": "candidate",
                        "full_name": "Candidate User",
                        "role": "user"
                    }])
                elif table_name == "events":
                    # Upcoming and past events organized
                    chain.execute.return_value = MagicMock(data=[
                        {"id": "ev-upcoming", "title": "Upcoming Fest", "start_datetime": future_iso, "status": "active"},
                        {"id": "ev-past", "title": "Past Meetup", "start_datetime": past_iso, "status": "active"}
                    ])
                elif table_name == "event_participants":
                    # Participants for upcoming event
                    chain.execute.return_value = MagicMock(data=[
                        {"id": 101, "event_id": "ev-joined-future", "user_id": "attendee-1"},
                    ])
                else:
                    chain.execute.return_value = MagicMock(data=[])
                return chain

            mock_sb.table.side_effect = table_router

            res = client.post("/api/admin/users/u-to-admin/grant-admin")
            assert res.status_code == 200
            data = res.json()
            assert data["role"] == "administrator"

            # Check that upcoming event was cancelled with reason
            event_cancellations = [payload for tbl, payload in events_updated if tbl == "events"]
            assert len(event_cancellations) == 1
            assert event_cancellations[0]["status"] == "cancelled"
            assert event_cancellations[0]["cancellation_reason"] == "Organizer was made an administrator"

            # Check that attendee was notified
            mock_notify.assert_called()
            notify_args = mock_notify.call_args[0]
            assert notify_args[0] == "attendee-1"
            assert notify_args[2] == "event_cancelled"
            assert "cancelled because organizer was made an administrator" in notify_args[3]

            # Check that friendships, friend_requests, user_blocks, saved_events, notifications were deleted
            assert "friendships" in deleted_tables
            assert "friend_requests" in deleted_tables
            assert "user_blocks" in deleted_tables
            assert "saved_events" in deleted_tables
            assert "notifications" in deleted_tables

            # Check profile update: bio, interests, phone, gender, banner_url reset to None
            profile_updates = [payload for tbl, payload in events_updated if tbl == "profiles"]
            assert len(profile_updates) == 1
            assert profile_updates[0]["role"] == "administrator"
            assert profile_updates[0]["bio"] is None
            assert profile_updates[0]["interests"] is None
            assert profile_updates[0]["phone"] is None
            assert profile_updates[0]["admin_since"] is not None
        finally:
            app.dependency_overrides.pop(require_admin, None)
