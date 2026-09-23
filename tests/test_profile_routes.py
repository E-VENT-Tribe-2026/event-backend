import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from app.main import app
from app.core.dependencies import get_current_user

client = TestClient(app)


class MockUser:
    id = "u1"
    email = "test@test.com"


class TestProfileRoutes:
    @patch("app.api.v1.profile_routes.get_profile")
    def test_get_my_profile_route_includes_username(self, mock_get):
        app.dependency_overrides[get_current_user] = lambda: MockUser()
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
            app.dependency_overrides.pop(get_current_user, None)

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
            mock_choose.assert_called_once_with("u1", "Bob", "Bob Smith")
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
            mock_choose.assert_called_once_with("u1", "Charlie", "Charlie Brown")
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
            mock_choose.assert_called_once_with("u1", "David", "David Miller")
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    @patch("app.api.v1.profile_routes.update_profile")
    def test_put_my_profile_update(self, mock_update):
        app.dependency_overrides[get_current_user] = lambda: MockUser()
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
            app.dependency_overrides.pop(get_current_user, None)
