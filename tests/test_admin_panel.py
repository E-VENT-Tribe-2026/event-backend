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
    @patch("app.services.admin_service.supabase")
    def test_list_admin_users(self, mock_sb):
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
        finally:
            app.dependency_overrides.pop(require_admin, None)

    # 5. User details with organized and joined events
    @patch("app.services.admin_service.supabase")
    def test_get_admin_user_details(self, mock_sb):
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
            select_chain = MagicMock()
            select_chain.select.return_value = select_chain
            select_chain.eq.return_value = select_chain
            select_chain.single.return_value = select_chain
            select_chain.execute.return_value = MagicMock(data={"id": "target-u1", "role": "user"})

            update_chain = MagicMock()
            update_chain.update.return_value = update_chain
            update_chain.eq.return_value = update_chain
            update_chain.execute.return_value = MagicMock(data=[{"id": "target-u1", "role": "administrator"}])

            mock_sb.table.side_effect = [select_chain, update_chain]

            res = client.post("/api/admin/users/target-u1/grant-admin")
            assert res.status_code == 200
            data = res.json()
            assert data["role"] == "administrator"
            assert data["user_id"] == "target-u1"
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
