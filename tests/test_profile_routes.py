import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from app.main import app
from app.core.dependencies import get_current_user, get_current_onboarded_user, get_own_profile_user

client = TestClient(app)

PROFILE_UUID = "123e4567-e89b-12d3-a456-426614174000"


class MockUser:
    id = "u1"
    email = "test@test.com"


class TestProfileRoutes:
    @patch("app.api.v1.profile_routes.get_profile")
    def test_get_my_profile_route_includes_username(self, mock_get):
        app.dependency_overrides[get_own_profile_user] = lambda: MockUser()
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
            app.dependency_overrides.pop(get_own_profile_user, None)

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
        app.dependency_overrides[get_own_profile_user] = lambda: MockUser()
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
            app.dependency_overrides.pop(get_own_profile_user, None)

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



TARGET_UUID = "223e4567-e89b-12d3-a456-426614174001"
VIEWER_UUID = "323e4567-e89b-12d3-a456-426614174002"


class RegularViewer:
    id = VIEWER_UUID
    email = "viewer@test.com"


class TestUserFriendsBlocking:
    """#226: the friends-list endpoint must respect blocks in both directions."""

    def setup_method(self):
        from app.core.dependencies import require_regular_user
        app.dependency_overrides[require_regular_user] = lambda: RegularViewer()

    def teardown_method(self):
        from app.core.dependencies import require_regular_user
        app.dependency_overrides.pop(require_regular_user, None)

    @patch("app.api.v1.profile_routes.get_user_friends_summary_page")
    @patch("app.api.v1.profile_routes.get_friendship_state")
    @patch("app.api.v1.profile_routes.get_public_profile")
    @patch("app.api.v1.profile_routes.has_blocked")
    def test_viewer_who_blocked_target_gets_403_and_no_friends(
        self, mock_blocked, mock_profile, mock_friendship, mock_friends
    ):
        mock_blocked.side_effect = lambda blocker, blocked: (blocker, blocked) == (VIEWER_UUID, TARGET_UUID)
        mock_profile.return_value = {"id": TARGET_UUID, "visibility": "public"}
        mock_friendship.return_value = {"status": "none"}

        response = client.get(f"/api/profile/{TARGET_UUID}/friends?page=1&limit=20")

        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "friends_list_unavailable"
        mock_friends.assert_not_called()

    @patch("app.api.v1.profile_routes.get_user_friends_summary_page")
    @patch("app.api.v1.profile_routes.has_blocked")
    def test_target_who_blocked_viewer_still_gets_404(self, mock_blocked, mock_friends):
        mock_blocked.side_effect = lambda blocker, blocked: (blocker, blocked) == (TARGET_UUID, VIEWER_UUID)

        response = client.get(f"/api/profile/{TARGET_UUID}/friends")

        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "profile_unavailable"
        mock_friends.assert_not_called()

    @patch("app.api.v1.profile_routes.get_user_friends_summary_page")
    @patch("app.api.v1.profile_routes.get_friendship_state")
    @patch("app.api.v1.profile_routes.get_public_profile")
    @patch("app.api.v1.profile_routes.has_blocked", return_value=False)
    def test_no_block_public_profile_returns_friends(
        self, mock_blocked, mock_profile, mock_friendship, mock_friends
    ):
        mock_profile.return_value = {"id": TARGET_UUID, "visibility": "public"}
        mock_friendship.return_value = {"status": "none"}
        mock_friends.return_value = {"data": [], "page": 1, "limit": 20, "has_more": False}

        response = client.get(f"/api/profile/{TARGET_UUID}/friends?page=1&limit=20")

        assert response.status_code == 200
        mock_friends.assert_called_once_with(TARGET_UUID, page=1, limit=20, viewer_id=VIEWER_UUID)