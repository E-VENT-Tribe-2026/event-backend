import base64
import json
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app
from app.core.dependencies import get_current_user, require_admin

client = TestClient(app)


def _create_jwt(payload: dict) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).decode().rstrip("=")
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{header}.{body}.sig"


class MockAdminUser:
    id = "admin-uuid-1"
    email = "admin@example.com"


class TestAdminPanel:
    """Test suite covering Ticket #151: Administrator Panel Data and Granting the Administrator Role."""

    # 1. Security Check: require_admin on all endpoints
    @patch("app.core.dependencies.supabase")
    def test_admin_endpoints_refuse_non_admin(self, mock_sb):
        valid_user = MagicMock()
        valid_user.id = "user-regular"
        mock_sb.auth.get_user.return_value = MagicMock(user=valid_user)

        profile_chain = MagicMock()
        profile_chain.select.return_value = profile_chain
        profile_chain.eq.return_value = profile_chain
        profile_chain.single.return_value = profile_chain
        profile_chain.execute.return_value = MagicMock(data={"role": "user"})
        mock_sb.table.return_value = profile_chain

        aal2_token = _create_jwt({"sub": "user-regular", "aal": "aal2"})
        headers = {"Authorization": f"Bearer {aal2_token}"}

        endpoints = [
            ("GET", "/api/admin/counts"),
            ("GET", "/api/admin/users"),
            ("GET", "/api/admin/users/some-id"),
            ("GET", "/api/admin/events"),
            ("GET", "/api/admin/events/some-id"),
            ("GET", "/api/admin/account"),
            ("POST", "/api/admin/users/some-id/grant-admin"),
        ]

        for method, url in endpoints:
            if method == "GET":
                res = client.get(url, headers=headers)
            else:
                res = client.post(url, headers=headers)
            assert res.status_code == 403, f"{method} {url} should refuse non-admin with 403"

    # 2. Total registered users & events counts
    @patch("app.services.admin_service.supabase")
    def test_get_admin_counts(self, mock_sb):
        app.dependency_overrides[require_admin] = lambda: MockAdminUser()
        try:
            now = datetime.now(timezone.utc)
            future_iso = (now + timedelta(days=5)).isoformat()
            past_iso = (now - timedelta(days=5)).isoformat()

            # Mock profiles count
            prof_chain = MagicMock()
            prof_chain.select.return_value = prof_chain
            prof_chain.execute.return_value = MagicMock(count=150, data=[])

            # Mock events list
            events_data = [
                {"id": "e1", "status": "active", "start_datetime": future_iso},
                {"id": "e2", "status": "active", "start_datetime": future_iso},
                {"id": "e3", "status": "completed", "start_datetime": past_iso},
                {"id": "e4", "status": "cancelled", "start_datetime": future_iso},  # Cancelled in future
                {"id": "e5", "status": "cancelled", "start_datetime": past_iso},    # Cancelled in past
            ]
            event_chain = MagicMock()
            event_chain.select.return_value = event_chain
            event_chain.execute.return_value = MagicMock(data=events_data)

            mock_sb.table.side_effect = lambda t: prof_chain if t == "profiles" else event_chain

            res = client.get("/api/admin/counts")
            assert res.status_code == 200
            data = res.json()
            assert data["total_users"] == 150
            # Cancelled events count ONLY as cancelled (2 cancelled)
            assert data["events"]["cancelled"] == 2
            # Upcoming = 2
            assert data["events"]["upcoming"] == 2
            # Past = 1
            assert data["events"]["past"] == 1
            assert data["events"]["total"] == 5
        finally:
            app.dependency_overrides.pop(require_admin, None)

    # 3. List users with pagination and search
    @patch("app.services.warning_service.supabase")
    @patch("app.services.admin_service.supabase")
    def test_list_admin_users(self, mock_sb, _mock_warnings_sb):
        app.dependency_overrides[require_admin] = lambda: MockAdminUser()
        try:
            users_data = [
                {"id": "u1", "username": "alice_w", "full_name": "Alice Wonderland", "avatar_url": None, "avatar_kind": "icon", "icon_id": "1", "role": "user", "created_at": "2026-01-01"},
                {"id": "u2", "username": None, "full_name": "Bob Builder", "avatar_url": "http://img", "avatar_kind": "photo", "icon_id": None, "role": "user", "created_at": "2026-01-02"},
            ]
            chain = MagicMock()
            chain.select.return_value = chain
            chain.ilike.return_value = chain
            chain.order.return_value = chain
            chain.range.return_value = chain
            chain.execute.return_value = MagicMock(count=2, data=users_data)
            mock_sb.table.return_value = chain

            res = client.get("/api/admin/users?search=alice&page=1&limit=10")
            assert res.status_code == 200
            data = res.json()
            assert data["total"] == 2
            assert data["page"] == 1
            assert len(data["items"]) == 2
            # Account with username
            assert data["items"][0]["display_name"] == "alice_w"
            # Account without username comes with its full name
            assert data["items"][1]["username"] is None
            assert data["items"][1]["display_name"] == "Bob Builder"
            assert data["items"][1]["full_name"] == "Bob Builder"
        finally:
            app.dependency_overrides.pop(require_admin, None)

    # 4. List events across four lists (all, past, upcoming, cancelled)
    @patch("app.services.admin_service.supabase")
    def test_list_admin_events_upcoming(self, mock_sb):
        app.dependency_overrides[require_admin] = lambda: MockAdminUser()
        try:
            ev_data = [
                {
                    "id": "e1",
                    "title": "Hackathon 2026",
                    "start_datetime": "2026-11-01T10:00:00Z",
                    "end_datetime": "2026-11-02T10:00:00Z",
                    "status": "active",
                    "created_by": "org-1"
                }
            ]
            event_chain = MagicMock()
            event_chain.select.return_value = event_chain
            event_chain.neq.return_value = event_chain
            event_chain.gte.return_value = event_chain
            event_chain.order.return_value = event_chain
            event_chain.range.return_value = event_chain
            event_chain.execute.return_value = MagicMock(count=1, data=ev_data)

            prof_chain = MagicMock()
            prof_chain.select.return_value = prof_chain
            prof_chain.in_.return_value = prof_chain
            prof_chain.execute.return_value = MagicMock(data=[
                {"id": "org-1", "username": "organizer_bob", "full_name": "Bob Organizer", "avatar_url": None, "avatar_kind": "icon", "icon_id": None}
            ])

            mock_sb.table.side_effect = lambda t: prof_chain if t == "profiles" else event_chain

            res = client.get("/api/admin/events?status_filter=upcoming")
            assert res.status_code == 200
            data = res.json()
            assert data["total"] == 1
            item = data["items"][0]
            assert item["title"] == "Hackathon 2026"
            assert item["is_cancelled"] is False
            assert item["organizer"]["username"] == "organizer_bob"
            assert item["organizer"]["full_name"] == "Bob Organizer"

            alias = client.get("/api/admin/events?filter=upcoming")
            assert alias.status_code == 200
            assert alias.json()["items"][0]["title"] == "Hackathon 2026"
        finally:
            app.dependency_overrides.pop(require_admin, None)

    @patch("app.services.admin_service.supabase")
    def test_list_admin_events_tolerates_missing_title_and_organizer(self, mock_sb):
        app.dependency_overrides[require_admin] = lambda: MockAdminUser()
        try:
            event_chain = MagicMock()
            event_chain.select.return_value = event_chain
            event_chain.order.return_value = event_chain
            event_chain.range.return_value = event_chain
            event_chain.execute.return_value = MagicMock(count=1, data=[
                {"id": "e-empty", "title": None, "start_datetime": None, "status": "active", "created_by": None},
            ])
            mock_sb.table.return_value = event_chain

            res = client.get("/api/admin/events/")
            assert res.status_code == 200
            item = res.json()["items"][0]
            assert item["id"] == "e-empty"
            assert item["title"] == ""
            assert item["organizer"] is None
        finally:
            app.dependency_overrides.pop(require_admin, None)

    # 5. User details with organized and joined events
    @patch("app.services.warning_service.supabase")
    @patch("app.services.admin_service.supabase")
    def test_get_admin_user_details(self, mock_sb, _mock_warnings_sb):
        app.dependency_overrides[require_admin] = lambda: MockAdminUser()
        try:
            now = datetime.now(timezone.utc)
            future_iso = (now + timedelta(days=2)).isoformat()
            past_iso = (now - timedelta(days=2)).isoformat()

            # Profile mock
            prof_chain = MagicMock()
            prof_chain.select.return_value = prof_chain
            prof_chain.eq.return_value = prof_chain
            prof_chain.single.return_value = prof_chain
            prof_chain.execute.return_value = MagicMock(data={
                "id": "target-u1",
                "username": "charlie",
                "full_name": "Charlie Chaplin",
                "avatar_url": None,
                "avatar_kind": "icon",
                "icon_id": None,
                "role": "user",
                "created_at": "2026-02-15T00:00:00Z"
            })

            # Organized events mock
            org_ev_chain = MagicMock()
            org_ev_chain.select.return_value = org_ev_chain
            org_ev_chain.eq.return_value = org_ev_chain
            org_ev_chain.order.return_value = org_ev_chain
            org_ev_chain.execute.return_value = MagicMock(data=[
                {"id": "ev-org-1", "title": "My Future Event", "start_datetime": future_iso, "status": "active"},
                {"id": "ev-org-2", "title": "My Cancelled Event", "start_datetime": future_iso, "status": "cancelled"},
            ])

            # Joined participants mock
            part_chain = MagicMock()
            part_chain.select.return_value = part_chain
            part_chain.eq.return_value = part_chain
            part_chain.execute.return_value = MagicMock(data=[{"event_id": "ev-joined-1"}])

            # Joined events query
            joined_ev_chain = MagicMock()
            joined_ev_chain.select.return_value = joined_ev_chain
            joined_ev_chain.in_.return_value = joined_ev_chain
            joined_ev_chain.order.return_value = joined_ev_chain
            joined_ev_chain.execute.return_value = MagicMock(data=[
                {"id": "ev-joined-1", "title": "Past Conference", "start_datetime": past_iso, "status": "completed"}
            ])

            def table_router(table_name):
                if table_name == "profiles":
                    return prof_chain
                if table_name == "event_participants":
                    return part_chain
                if table_name == "events":
                    # Alternate between organized query and joined events query
                    return org_ev_chain if org_ev_chain.execute.call_count == 0 else joined_ev_chain
                return MagicMock()

            mock_sb.table.side_effect = table_router

            res = client.get("/api/admin/users/target-u1")
            assert res.status_code == 200
            data = res.json()
            assert data["id"] == "target-u1"
            assert data["username"] == "charlie"
            assert data["is_admin"] is False
            assert len(data["organized_events"]["upcoming"]) == 1
            assert len(data["organized_events"]["cancelled"]) == 1
            assert len(data["joined_events"]["past"]) == 1
        finally:
            app.dependency_overrides.pop(require_admin, None)

    # 6. Event full details with participants
    @patch("app.services.admin_service.supabase")
    def test_get_admin_event_details(self, mock_sb):
        app.dependency_overrides[require_admin] = lambda: MockAdminUser()
        try:
            # Event mock
            ev_chain = MagicMock()
            ev_chain.select.return_value = ev_chain
            ev_chain.eq.return_value = ev_chain
            ev_chain.single.return_value = ev_chain
            ev_chain.execute.return_value = MagicMock(data={
                "id": "e-100",
                "title": "Music Fest",
                "description": "Fun fest",
                "category": "Music",
                "start_datetime": "2026-12-01T12:00:00Z",
                "end_datetime": "2026-12-01T20:00:00Z",
                "location_name": "Park",
                "latitude": 10.0,
                "longitude": 20.0,
                "cost": 50,
                "max_capacity": 500,
                "status": "active",
                "created_by": "org-id-1"
            })

            # Organizer profile mock
            org_chain = MagicMock()
            org_chain.select.return_value = org_chain
            org_chain.eq.return_value = org_chain
            org_chain.single.return_value = org_chain
            org_chain.execute.return_value = MagicMock(data={
                "id": "org-id-1",
                "username": "event_planner",
                "full_name": "Eva Planner",
                "avatar_url": None,
                "avatar_kind": "icon",
                "icon_id": None
            })

            # Participants mock
            part_chain = MagicMock()
            part_chain.select.return_value = part_chain
            part_chain.eq.return_value = part_chain
            part_chain.order.return_value = part_chain
            part_chain.execute.return_value = MagicMock(data=[
                {"id": 1, "user_id": "part-u1", "status": "registered", "created_at": "2026-10-01T00:00:00Z"}
            ])

            # Participant profiles batch
            part_prof_chain = MagicMock()
            part_prof_chain.select.return_value = part_prof_chain
            part_prof_chain.in_.return_value = part_prof_chain
            part_prof_chain.execute.return_value = MagicMock(data=[
                {"id": "part-u1", "username": "fan1", "full_name": "Music Fan", "avatar_url": None, "avatar_kind": "icon", "icon_id": None}
            ])

            def table_router(table_name):
                if table_name == "events":
                    return ev_chain
                if table_name == "event_participants":
                    return part_chain
                if table_name == "profiles":
                    return org_chain if org_chain.execute.call_count == 0 else part_prof_chain
                return MagicMock()

            mock_sb.table.side_effect = table_router

            res = client.get("/api/admin/events/e-100")
            assert res.status_code == 200
            data = res.json()
            assert data["id"] == "e-100"
            assert data["title"] == "Music Fest"
            assert data["organizer"]["username"] == "event_planner"
            assert data["participant_count"] == 1
            assert data["participants"][0]["username"] == "fan1"
            assert data["participants"][0]["full_name"] == "Music Fan"
        finally:
            app.dependency_overrides.pop(require_admin, None)

    # 7. Grant administrator role
    @patch("app.services.admin_service.supabase")
    def test_grant_admin_role_success(self, mock_sb):
        app.dependency_overrides[require_admin] = lambda: MockAdminUser()
        try:
            now = datetime.now(timezone.utc)
            future_iso = (now + timedelta(days=2)).isoformat()

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
                    # select target profile then update
                    chain.execute.return_value = MagicMock(data=[{
                        "id": "target-u1",
                        "username": "alice",
                        "full_name": "Alice Wonderland",
                        "role": "user"
                    }])
                elif table_name == "events":
                    chain.execute.return_value = MagicMock(data=[
                        {"id": "ev-1", "title": "Upcoming Event", "start_datetime": future_iso, "status": "active"}
                    ])
                elif table_name == "event_participants":
                    chain.execute.return_value = MagicMock(data=[
                        {"id": "p-1", "user_id": "other-u2"}
                    ])
                else:
                    chain.execute.return_value = MagicMock(data=[])
                return chain

            mock_sb.table.side_effect = table_router

            res = client.post("/api/admin/users/target-u1/grant-admin")
            assert res.status_code == 200
            data = res.json()
            assert data["role"] == "administrator"
            assert data["user_id"] == "target-u1"
            assert "admin_since" in data
            assert data["summary"]["cancelled_events_count"] == 1
        finally:
            app.dependency_overrides.pop(require_admin, None)

    @patch("app.services.admin_service.supabase")
    def test_grant_admin_role_refuses_existing_admin(self, mock_sb):
        app.dependency_overrides[require_admin] = lambda: MockAdminUser()
        try:
            select_chain = MagicMock()
            select_chain.select.return_value = select_chain
            select_chain.eq.return_value = select_chain
            select_chain.single.return_value = select_chain
            select_chain.execute.return_value = MagicMock(data={"id": "admin-u2", "role": "administrator"})
            mock_sb.table.return_value = select_chain

            res = client.post("/api/admin/users/admin-u2/grant-admin")
            assert res.status_code == 400
            assert "already an administrator" in res.json()["detail"].lower()
        finally:
            app.dependency_overrides.pop(require_admin, None)

    # 8. Ticket #194: Event Details Returns Chat for upcoming, past, and cancelled events
    @pytest.mark.parametrize("event_status,start_dt", [
        ("upcoming", (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()),
        ("past", (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()),
        ("cancelled", (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()),
    ])
    @patch("app.services.admin_service.supabase")
    def test_get_admin_event_details_includes_chat_messages(self, mock_sb, event_status, start_dt):
        app.dependency_overrides[require_admin] = lambda: MockAdminUser()
        try:
            is_cancelled = (event_status == "cancelled")
            ev_chain = MagicMock()
            ev_chain.select.return_value = ev_chain
            ev_chain.eq.return_value = ev_chain
            ev_chain.single.return_value = ev_chain
            ev_chain.execute.return_value = MagicMock(data={
                "id": f"event-{event_status}",
                "title": f"Event {event_status.capitalize()}",
                "description": "Event Description",
                "category": "Tech",
                "start_datetime": start_dt,
                "end_datetime": start_dt,
                "location_name": "Auditorium",
                "latitude": 12.34,
                "longitude": 56.78,
                "cost": 10.0,
                "max_capacity": 100,
                "status": "cancelled" if is_cancelled else "active",
                "created_by": "org-id-1",
            })

            org_chain = MagicMock()
            org_chain.select.return_value = org_chain
            org_chain.eq.return_value = org_chain
            org_chain.single.return_value = org_chain
            org_chain.execute.return_value = MagicMock(data={
                "id": "org-id-1",
                "username": "organizer_user",
                "full_name": "Organizer One",
                "avatar_url": "https://img.com/org.png",
                "avatar_kind": "photo",
                "icon_id": None,
            })

            part_chain = MagicMock()
            part_chain.select.return_value = part_chain
            part_chain.eq.return_value = part_chain
            part_chain.order.return_value = part_chain
            part_chain.execute.return_value = MagicMock(data=[
                {"id": 1, "user_id": "user-chat-1", "status": "registered", "created_at": "2026-10-01T00:00:00Z"}
            ])

            chat_chain = MagicMock()
            chat_chain.select.return_value = chat_chain
            chat_chain.eq.return_value = chat_chain
            chat_chain.order.return_value = chat_chain
            chat_chain.execute.return_value = MagicMock(data=[
                {
                    "id": 101,
                    "event_id": f"event-{event_status}",
                    "sender_id": "user-chat-1",
                    "content": "Hello everyone!",
                    "type": "chat",
                    "created_at": "2026-10-01T12:00:00Z",
                },
                {
                    "id": 102,
                    "event_id": f"event-{event_status}",
                    "sender_id": None,
                    "content": "Welcome to the event chat!",
                    "type": "notification",
                    "created_at": "2026-10-01T11:00:00Z",
                },
            ])

            prof_chain = MagicMock()
            prof_chain.select.return_value = prof_chain
            prof_chain.in_.return_value = prof_chain
            prof_chain.execute.return_value = MagicMock(data=[
                {
                    "id": "user-chat-1",
                    "username": "chatty_user",
                    "full_name": "Chatty Person",
                    "avatar_url": "https://img.com/avatar1.png",
                    "avatar_kind": "photo",
                    "icon_id": None,
                }
            ])

            def table_router(table_name):
                if table_name == "events":
                    return ev_chain
                if table_name == "event_participants":
                    return part_chain
                if table_name == "event_chats":
                    return chat_chain
                if table_name == "profiles":
                    return org_chain if org_chain.execute.call_count == 0 else prof_chain
                return MagicMock()

            mock_sb.table.side_effect = table_router

            res = client.get(f"/api/admin/events/event-{event_status}")
            assert res.status_code == 200
            data = res.json()
            assert data["id"] == f"event-{event_status}"
            assert data["is_cancelled"] == is_cancelled

            # Verify chat messages are included
            assert "chats" in data
            assert "chat" in data
            assert len(data["chats"]) == 2

            # Check regular user message
            user_msg = next(m for m in data["chats"] if m["id"] == 101)
            assert user_msg["sender_id"] == "user-chat-1"
            assert user_msg["username"] == "chatty_user"
            assert user_msg["full_name"] == "Chatty Person"
            assert user_msg["avatar_url"] == "https://img.com/avatar1.png"
            assert user_msg["text"] == "Hello everyone!"
            assert user_msg["time"] == "2026-10-01T12:00:00Z"
            assert user_msg["is_system_message"] is False

            # Check system message
            sys_msg = next(m for m in data["chats"] if m["id"] == 102)
            assert sys_msg["sender_id"] is None
            assert sys_msg["text"] == "Welcome to the event chat!"
            assert sys_msg["time"] == "2026-10-01T11:00:00Z"
            assert sys_msg["is_system_message"] is True
        finally:
            app.dependency_overrides.pop(require_admin, None)

    # 9. Ticket #194: Refuse user account requesting event details through admin panel
    @patch("app.core.dependencies.supabase")
    def test_admin_event_details_refuses_regular_user_account(self, mock_sb):
        valid_user = MagicMock()
        valid_user.id = "regular-user-id"
        mock_sb.auth.get_user.return_value = MagicMock(user=valid_user)

        profile_chain = MagicMock()
        profile_chain.select.return_value = profile_chain
        profile_chain.eq.return_value = profile_chain
        profile_chain.single.return_value = profile_chain
        profile_chain.execute.return_value = MagicMock(data={"role": "user"})
        mock_sb.table.return_value = profile_chain

        aal2_token = _create_jwt({"sub": "regular-user-id", "aal": "aal2"})
        headers = {"Authorization": f"Bearer {aal2_token}"}

        res = client.get("/api/admin/events/any-event-id", headers=headers)
        assert res.status_code == 403
        assert "Forbidden" in res.json()["detail"]

    # 10. Administrator Account Details Endpoint
    @patch("app.services.admin_service.supabase")
    def test_get_admin_account_details(self, mock_sb):
        app.dependency_overrides[require_admin] = lambda: MockAdminUser()
        try:
            chain = MagicMock()
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.single.return_value = chain
            chain.execute.return_value = MagicMock(data={
                "id": "admin-uuid-1",
                "username": "admin_boss",
                "full_name": "Admin Boss",
                "avatar_url": "https://img.com/admin.png",
                "avatar_kind": "photo",
                "icon_id": None,
                "admin_since": "2026-03-01T12:00:00Z",
                "role": "administrator",
            })
            mock_sb.table.return_value = chain

            res = client.get("/api/admin/account")
            assert res.status_code == 200
            data = res.json()
            assert data["id"] == "admin-uuid-1"
            assert data["username"] == "admin_boss"
            assert data["full_name"] == "Admin Boss"
            assert data["admin_since"] == "2026-03-01T12:00:00Z"
            assert data["role"] == "administrator"
        finally:
            app.dependency_overrides.pop(require_admin, None)

    # 11. User Details says whether account is administrator, since when, and empty warning history
    @patch("app.services.admin_service.supabase")
    def test_admin_user_details_returns_admin_since_and_no_warnings(self, mock_sb):
        app.dependency_overrides[require_admin] = lambda: MockAdminUser()
        try:
            prof_chain = MagicMock()
            prof_chain.select.return_value = prof_chain
            prof_chain.eq.return_value = prof_chain
            prof_chain.single.return_value = prof_chain
            prof_chain.execute.return_value = MagicMock(data={
                "id": "admin-user-target",
                "username": "former_user",
                "full_name": "Former User",
                "avatar_url": None,
                "avatar_kind": "icon",
                "icon_id": None,
                "role": "administrator",
                "admin_since": "2026-04-10T10:00:00Z",
                "created_at": "2026-01-01T00:00:00Z",
            })

            empty_chain = MagicMock()
            empty_chain.select.return_value = empty_chain
            empty_chain.eq.return_value = empty_chain
            empty_chain.order.return_value = empty_chain
            empty_chain.execute.return_value = MagicMock(data=[])

            def table_router(table_name):
                if table_name == "profiles":
                    return prof_chain
                return empty_chain

            mock_sb.table.side_effect = table_router

            res = client.get("/api/admin/users/admin-user-target")
            assert res.status_code == 200
            data = res.json()
            assert data["is_admin"] is True
            assert data["admin_since"] == "2026-04-10T10:00:00Z"
            assert data["warnings"] == []
            assert data["warning_history"] == []
        finally:
            app.dependency_overrides.pop(require_admin, None)

    # 12. Panel Event Details includes cancellation reason and participant admin status
    @patch("app.services.admin_service.supabase")
    def test_admin_event_details_includes_cancellation_reason_and_participant_admin_flag(self, mock_sb):
        app.dependency_overrides[require_admin] = lambda: MockAdminUser()
        try:
            ev_chain = MagicMock()
            ev_chain.select.return_value = ev_chain
            ev_chain.eq.return_value = ev_chain
            ev_chain.single.return_value = ev_chain
            ev_chain.execute.return_value = MagicMock(data={
                "id": "cancelled-ev-1",
                "title": "Cancelled Event",
                "start_datetime": "2026-11-01T10:00:00Z",
                "status": "cancelled",
                "cancellation_reason": "Organizer was made an administrator",
                "created_by": "org-1",
            })

            org_chain = MagicMock()
            org_chain.select.return_value = org_chain
            org_chain.eq.return_value = org_chain
            org_chain.single.return_value = org_chain
            org_chain.execute.return_value = MagicMock(data={
                "id": "org-1",
                "username": "organizer_one",
                "full_name": "Organizer One",
                "avatar_url": None,
                "avatar_kind": "icon",
                "icon_id": None,
            })

            part_chain = MagicMock()
            part_chain.select.return_value = part_chain
            part_chain.eq.return_value = part_chain
            part_chain.order.return_value = part_chain
            part_chain.execute.return_value = MagicMock(data=[
                {"id": 1, "user_id": "u-admin-part", "status": "registered", "created_at": "2026-10-01T00:00:00Z"}
            ])

            prof_chain = MagicMock()
            prof_chain.select.return_value = prof_chain
            prof_chain.in_.return_value = prof_chain
            prof_chain.execute.return_value = MagicMock(data=[
                {
                    "id": "u-admin-part",
                    "username": "now_admin",
                    "full_name": "Now Admin",
                    "avatar_url": None,
                    "avatar_kind": "icon",
                    "icon_id": None,
                    "role": "administrator",
                }
            ])

            chat_chain = MagicMock()
            chat_chain.select.return_value = chat_chain
            chat_chain.eq.return_value = chat_chain
            chat_chain.order.return_value = chat_chain
            chat_chain.execute.return_value = MagicMock(data=[])

            def table_router(table_name):
                if table_name == "events":
                    return ev_chain
                if table_name == "event_participants":
                    return part_chain
                if table_name == "event_chats":
                    return chat_chain
                if table_name == "profiles":
                    # First profile query is organizer (.eq), second is participants (.in_)
                    return org_chain if org_chain.execute.call_count == 0 else prof_chain
                return MagicMock()

            mock_sb.table.side_effect = table_router

            res = client.get("/api/admin/events/cancelled-ev-1")
            assert res.status_code == 200
            data = res.json()
            assert data["is_cancelled"] is True
            assert data["cancellation_reason"] == "Organizer was made an administrator"
            assert len(data["participants"]) == 1
            assert data["participants"][0]["is_admin"] is True
        finally:
            app.dependency_overrides.pop(require_admin, None)

    # 13. Refuse administrator accounts every user function
    @patch("app.core.dependencies.supabase")
    def test_administrator_refused_user_functions(self, mock_sb):
        admin_user = MagicMock()
        admin_user.id = "admin-user-id"
        mock_sb.auth.get_user.return_value = MagicMock(user=admin_user)

        profile_chain = MagicMock()
        profile_chain.select.return_value = profile_chain
        profile_chain.eq.return_value = profile_chain
        profile_chain.single.return_value = profile_chain
        profile_chain.execute.return_value = MagicMock(data={
            "id": "admin-user-id",
            "username": "admin_account",
            "full_name": "Admin Account",
            "role": "administrator"
        })
        mock_sb.table.return_value = profile_chain

        admin_token = _create_jwt({"sub": "admin-user-id", "aal": "aal2"})
        headers = {"Authorization": f"Bearer {admin_token}"}

        # User endpoints that must be refused to administrators
        endpoints = [
            ("POST", "/api/events/", {"title": "Test Event", "category": "party"}),
            ("PUT", "/api/profile/me", {"bio": "Hello"}),
            ("POST", "/api/friends/requests", {"receiver_id": "00000000-0000-0000-0000-000000000002"}),
            ("POST", "/api/blocks", {"user_id": "00000000-0000-0000-0000-000000000002"}),
            ("POST", "/api/favorites/save-events/some-event-id", None),
        ]

        for method, url, body in endpoints:
            if method == "POST":
                res = client.post(url, json=body or {}, headers=headers)
            elif method == "PUT":
                res = client.put(url, json=body or {}, headers=headers)
            elif method == "GET":
                res = client.get(url, headers=headers)

            assert res.status_code == 403, f"{method} {url} should refuse administrator account with 403"
            assert "Administrator accounts cannot perform user actions." in res.json()["detail"]

    @patch("app.api.v1.profile_routes.get_profile")
    @patch("app.core.dependencies.supabase")
    def test_administrator_can_read_own_profile_after_mfa(self, mock_sb, mock_get):
        admin_user = MagicMock()
        admin_user.id = "admin-user-id"
        mock_sb.auth.get_user.return_value = MagicMock(user=admin_user)

        profile_chain = MagicMock()
        profile_chain.select.return_value = profile_chain
        profile_chain.eq.return_value = profile_chain
        profile_chain.single.return_value = profile_chain
        profile_chain.execute.return_value = MagicMock(data={
            "id": "admin-user-id",
            "username": "admin_account",
            "full_name": "Admin Account",
            "role": "administrator",
        })
        mock_sb.table.return_value = profile_chain
        mock_get.return_value = {
            "id": "admin-user-id",
            "username": "admin_account",
            "role": "administrator",
        }

        admin_token = _create_jwt({"sub": "admin-user-id", "aal": "aal2"})
        res = client.get("/api/profile/me", headers={"Authorization": f"Bearer {admin_token}"})
        assert res.status_code == 200
        assert res.json()["role"] == "administrator"
        mock_get.assert_called_once_with("admin-user-id")

    @patch("app.services.warning_service.supabase")
    @patch("app.services.admin_service.supabase")
    @patch("app.core.dependencies.supabase")
    def test_administrator_can_fetch_users_after_mfa(self, mock_dep_sb, mock_admin_sb, _mock_warn_sb):
        admin_user = MagicMock()
        admin_user.id = "admin-user-id"
        mock_dep_sb.auth.get_user.return_value = MagicMock(user=admin_user)
        profile_chain = MagicMock()
        profile_chain.select.return_value = profile_chain
        profile_chain.eq.return_value = profile_chain
        profile_chain.single.return_value = profile_chain
        profile_chain.execute.return_value = MagicMock(data={"role": "administrator"})
        mock_dep_sb.table.return_value = profile_chain

        users_chain = MagicMock()
        users_chain.select.return_value = users_chain
        users_chain.order.return_value = users_chain
        users_chain.range.return_value = users_chain
        users_chain.execute.return_value = MagicMock(count=1, data=[
            {"id": "u1", "username": "alice", "full_name": "Alice", "role": "user", "created_at": "2026-01-01"},
        ])
        mock_admin_sb.table.return_value = users_chain

        admin_token = _create_jwt({"sub": "admin-user-id", "aal": "aal2"})
        headers = {"Authorization": f"Bearer {admin_token}"}
        res = client.get("/api/admin/users", headers=headers)
        assert res.status_code == 200
        assert res.json()["items"][0]["username"] == "alice"

        empty_filter = client.get("/api/admin/users?filter=", headers=headers)
        assert empty_filter.status_code == 200

        trailing = client.get("/api/admin/users/", headers=headers)
        assert trailing.status_code == 200

    @patch("app.services.admin_service.supabase")
    @patch("app.core.dependencies.supabase")
    def test_administrator_can_fetch_events_after_mfa(self, mock_dep_sb, mock_admin_sb):
        admin_user = MagicMock()
        admin_user.id = "admin-user-id"
        mock_dep_sb.auth.get_user.return_value = MagicMock(user=admin_user)
        profile_chain = MagicMock()
        profile_chain.select.return_value = profile_chain
        profile_chain.eq.return_value = profile_chain
        profile_chain.single.return_value = profile_chain
        profile_chain.execute.return_value = MagicMock(data={"role": "administrator"})
        mock_dep_sb.table.return_value = profile_chain

        event_chain = MagicMock()
        event_chain.select.return_value = event_chain
        event_chain.order.return_value = event_chain
        event_chain.range.return_value = event_chain
        event_chain.execute.return_value = MagicMock(count=1, data=[
            {"id": "e1", "title": "Meetup", "start_datetime": "2026-11-01T10:00:00Z", "status": "active", "created_by": None},
        ])
        mock_admin_sb.table.return_value = event_chain

        admin_token = _create_jwt({"sub": "admin-user-id", "aal": "aal2"})
        headers = {"Authorization": f"Bearer {admin_token}"}
        res = client.get("/api/admin/events/", headers=headers)
        assert res.status_code == 200
        assert res.json()["items"][0]["title"] == "Meetup"

        aliased = client.get("/api/admin/events?filter=all", headers=headers)
        assert aliased.status_code == 200

    def test_remaining_admin_gets_accept_trailing_slash(self):
        app.dependency_overrides[require_admin] = lambda: MockAdminUser()
        cases = [
            ("/api/admin/verify/", None, None),
            ("/api/admin/account/", "app.api.v1.admin_routes.get_admin_account_details", {
                "id": "a1", "role": "administrator",
            }),
            ("/api/admin/counts/", "app.api.v1.admin_routes.get_admin_counts", {
                "total_users": 0, "events": {"total": 0, "upcoming": 0, "past": 0, "cancelled": 0},
            }),
            ("/api/admin/users/counters/", "app.api.v1.admin_routes.get_user_list_counters", {
                "administrators": 0, "suspended": 0, "with_warnings": 0,
            }),
            ("/api/admin/users/u1/", "app.api.v1.admin_routes.get_admin_user_details", {
                "id": "u1",
                "organized_events": {"upcoming": [], "past": [], "cancelled": []},
                "joined_events": {"upcoming": [], "past": [], "cancelled": []},
            }),
            ("/api/admin/events/e1/", "app.api.v1.admin_routes.get_admin_event_details", {
                "id": "e1", "title": "Meetup", "participants": [], "chats": [], "chat": [],
            }),
            ("/api/admin/users/u1/warnings/", "app.api.v1.admin_routes.get_warning_history", {
                "user_id": "u1", "items": [],
            }),
            ("/api/admin/audit-log/", "app.api.v1.admin_routes.list_audit_log", {
                "items": [], "has_more": False, "next_before": None,
            }),
        ]
        try:
            for url, target, payload in cases:
                if target:
                    with patch(target, return_value=payload):
                        res = client.get(url)
                else:
                    res = client.get(url)
                assert res.status_code == 200, f"{url} returned {res.status_code}: {res.text}"
        finally:
            app.dependency_overrides.pop(require_admin, None)
