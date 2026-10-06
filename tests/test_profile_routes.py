import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from app.main import app
from app.core.dependencies import get_current_user, get_current_onboarded_user

client = TestClient(app)

PROFILE_UUID = "123e4567-e89b-12d3-a456-426614174000"


class MockUser:
    id = "u1"
    email = "test@test.com"


class TestProfileRoutes:
    @patch("app.api.v1.profile_routes.get_profile")
    def test_get_my_profile_route_includes_username(self, mock_get):
        app.dependency_overrides[get_current_onboarded_user] = lambda: MockUser()
        try:
            mock_get.return_value = {
                "id": "u1",
                "username": "alice",
                "full_name": "Alice Smith"
            }
            response = client.get("/api/profile/me", headers={"Authorization": "Bearer token"})
            assert response.status_code == 200
            assert response.json()["username"] == "alice"
            assert response.json()["full_name"] == "Alice Smith"
            mock_get.assert_called_once_with("u1")
        finally:
            app.dependency_overrides.pop(get_current_onboarded_user, None)

    @patch("app.api.v1.profile_routes.choose_username")
    def test_post_choose_username_route(self, mock_choose):
        app.dependency_overrides[get_current_user] = lambda: MockUser()
        try:
            mock_choose.return_value = {
                "id": "u1",
                "username": "bob",
                "full_name": "Bob Smith"
            }
            response = client.post(
                "/api/profile/choose-username",
                json={"username": "Bob", "full_name": "Bob Smith"},
                headers={"Authorization": "Bearer token"}
            )
            assert response.status_code == 200
            assert response.json()["username"] == "bob"
            mock_choose.assert_called_once_with("u1", "bob", "Bob Smith")
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    @patch("app.api.v1.profile_routes.choose_username")
    def test_post_username_route(self, mock_choose):
        app.dependency_overrides[get_current_user] = lambda: MockUser()
        try:
            mock_choose.return_value = {
                "id": "u1",
                "username": "charlie",
                "full_name": "Charlie Brown"
            }
            response = client.post(
                "/api/profile/username",
                json={"username": "Charlie", "full_name": "Charlie Brown"},
                headers={"Authorization": "Bearer token"}
            )
            assert response.status_code == 200
            assert response.json()["username"] == "charlie"
            mock_choose.assert_called_once_with("u1", "charlie", "Charlie Brown")
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    @patch("app.api.v1.profile_routes.choose_username")
    def test_put_username_route(self, mock_choose):
        app.dependency_overrides[get_current_user] = lambda: MockUser()
        try:
            mock_choose.return_value = {
                "id": "u1",
                "username": "david",
                "full_name": "David Miller"
            }
            response = client.put(
                "/api/profile/username",
                json={"username": "David", "full_name": "David Miller"},
                headers={"Authorization": "Bearer token"}
            )
            assert response.status_code == 200
            assert response.json()["username"] == "david"
            mock_choose.assert_called_once_with("u1", "david", "David Miller")
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    @patch("app.api.v1.profile_routes.update_profile")
    def test_put_my_profile_update(self, mock_update):
        app.dependency_overrides[get_current_onboarded_user] = lambda: MockUser()
        try:
            mock_update.return_value = {
                "id": "u1",
                "full_name": "Jane Doe"
            }
            response = client.put(
                "/api/profile/me",
                json={"full_name": "Jane Doe"},
                headers={"Authorization": "Bearer token"}
            )
            assert response.status_code == 200
            mock_update.assert_called_once_with("u1", {"full_name": "Jane Doe"})
        finally:
            app.dependency_overrides.pop(get_current_onboarded_user, None)

    @patch("app.api.v1.profile_routes.get_profile")
    def test_get_my_profile_route_includes_banner_and_avatar_kind(self, mock_get):
        app.dependency_overrides[get_current_onboarded_user] = lambda: MockUser()
        try:
            mock_get.return_value = {
                "id": "u1",
                "username": "alice",
                "full_name": "Alice Smith",
                "banner": "banner_aurora",
                "banner_url": "banner_aurora",
                "avatar_kind": "icon",
                "icon_id": "icon_fox"
            }
            response = client.get("/api/profile/me", headers={"Authorization": "Bearer token"})
            assert response.status_code == 200
            data = response.json()
            assert data["username"] == "alice"
            assert data["banner"] == "banner_aurora"
            assert data["avatar_kind"] == "icon"
            assert data["icon_id"] == "icon_fox"
        finally:
            app.dependency_overrides.pop(get_current_onboarded_user, None)

    @patch("app.api.v1.profile_routes.update_profile")
    def test_put_my_profile_accepts_banner_and_avatar_kind(self, mock_update):
        app.dependency_overrides[get_current_onboarded_user] = lambda: MockUser()
        try:
            mock_update.return_value = {
                "id": "u1",
                "banner": "banner_beach",
                "banner_url": "banner_beach",
                "avatar_kind": "photo",
                "avatar_url": "https://example.com/me.png"
            }
            response = client.put(
                "/api/profile/me",
                json={
                    "banner": "banner_beach",
                    "avatar_kind": "photo",
                    "avatar_url": "https://example.com/me.png"
                },
                headers={"Authorization": "Bearer token"}
            )
            assert response.status_code == 200
            mock_update.assert_called_once_with("u1", {
                "banner": "banner_beach",
                "avatar_kind": "photo",
                "avatar_url": "https://example.com/me.png"
            })
        finally:
            app.dependency_overrides.pop(get_current_onboarded_user, None)

    def test_put_my_profile_unauthenticated(self):
        # When no user is authenticated, updating own profile is refused
        response = client.put(
            "/api/profile/me",
            json={"full_name": "Stranger"}
        )
        assert response.status_code in (401, 403)


class TestProfileSearchAndPublicRoutes:
    @patch("app.api.v1.profile_routes.search_profiles")
    def test_search_passes_viewer_id(self, mock_search):
        app.dependency_overrides[get_current_user] = lambda: MockUser()
        try:
            mock_search.return_value = {"page": 2, "limit": 5, "has_more": False, "data": []}
            response = client.get(
                "/api/profile/search?q=alice&page=2&limit=5",
                headers={"Authorization": "Bearer token"},
            )
            assert response.status_code == 200
            assert response.json()["has_more"] is False
            mock_search.assert_called_once_with("alice", 2, 5, "u1")
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    @pytest.mark.parametrize("params", ["limit=0", "limit=-1", "limit=51", "page=10001"])
    @patch("app.api.v1.profile_routes.search_profiles")
    def test_search_rejects_out_of_range_pagination(self, mock_search, params):
        app.dependency_overrides[get_current_user] = lambda: MockUser()
        try:
            response = client.get(
                f"/api/profile/search?q=alice&{params}",
                headers={"Authorization": "Bearer token"},
            )
            assert response.status_code == 422
            mock_search.assert_not_called()
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    @patch("app.api.v1.profile_routes.build_public_profile")
    def test_get_public_profile_passes_viewer_id(self, mock_build):
        app.dependency_overrides[get_current_user] = lambda: MockUser()
        try:
            mock_build.return_value = {
                "id": PROFILE_UUID,
                "username": "bob",
                "events": {
                    "organized": {"upcoming": [], "past": []},
                    "joined": {"upcoming": [], "past": []},
                },
                "friendship": {"status": "none", "request_id": None},
            }
            response = client.get(
                f"/api/profile/{PROFILE_UUID}",
                headers={"Authorization": "Bearer token"},
            )
            assert response.status_code == 200
            assert response.json()["id"] == PROFILE_UUID
            mock_build.assert_called_once_with(PROFILE_UUID, "u1")
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    @patch("app.api.v1.profile_routes.build_public_profile")
    def test_get_public_profile_non_uuid_returns_422(self, mock_build):
        app.dependency_overrides[get_current_user] = lambda: MockUser()
        try:
            response = client.get(
                "/api/profile/not-a-uuid",
                headers={"Authorization": "Bearer token"},
            )
            assert response.status_code == 422
            mock_build.assert_not_called()
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    def test_search_requires_authentication(self):
        response = client.get("/api/profile/search?q=alice")
        assert response.status_code in (401, 403)

    def test_get_public_profile_requires_authentication(self):
        response = client.get(f"/api/profile/{PROFILE_UUID}")
        assert response.status_code in (401, 403)
