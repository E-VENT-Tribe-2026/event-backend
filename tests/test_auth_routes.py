import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from app.main import app

client = TestClient(app)

class TestAuthRoutes:
    @patch("app.api.v1.auth_routes.register_user")
    def test_register_route(self, mock_register):
        mock_register.return_value = {"access_token": "token", "user_id": "u1"}

        payload = {
            "email": "test@test.com",
            "password": "password123",
            "invite_code": "ABCD-EFGH",
            "username": "testuser",
            "full_name": "Test User",
            "dob": "1990-01-01",
            "gender": "male",
            "interests": ["coding"]
        }

        response = client.post("/api/auth/register", json=payload)

        assert response.status_code == 200
        assert response.json() == {"access_token": "token", "user_id": "u1"}
        mock_register.assert_called_once_with(
            email="test@test.com",
            password="password123",
            full_name="Test User",
            dob="1990-01-01",
            gender="male",
            interests=["coding"],
            username="testuser",
            invite_code="ABCD-EFGH",
        )

    @patch("app.services.profile_service.choose_username")
    def test_auth_choose_username_route(self, mock_choose):
        class MockUser:
            id = "u1"
            email = "test@test.com"

        from app.core.dependencies import get_current_user
        app.dependency_overrides[get_current_user] = lambda: MockUser()

        try:
            mock_choose.return_value = {"id": "u1", "username": "alice", "full_name": "Alice Wonderland"}
            response = client.post("/api/auth/choose-username", json={
                "username": "Alice",
                "full_name": "Alice Wonderland"
            }, headers={"Authorization": "Bearer token"})

            assert response.status_code == 200
            assert response.json()["username"] == "alice"
            mock_choose.assert_called_once_with(
                user_id="u1",
                username="alice",
                full_name="Alice Wonderland"
            )
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    @patch("app.api.v1.auth_routes.login_user")
    def test_login_route(self, mock_login):
        mock_login.return_value = {"access_token": "token", "token_type": "bearer"}

        response = client.post("/api/auth/login", json={
            "email": "test@test.com",
            "password": "password123"
        })

        assert response.status_code == 200
        assert response.json()["access_token"] == "token"

    @patch("app.api.v1.auth_routes.change_password")
    def test_change_password_route(self, mock_change_password):
        class MockUser:
            id = "u1"
            email = "test@test.com"

        def override_get_current_onboarded_user():
            return MockUser()

        from app.core.dependencies import get_current_user, get_current_onboarded_user
        app.dependency_overrides[get_current_onboarded_user] = override_get_current_onboarded_user

        try:
            mock_change_password.return_value = {"message": "Password updated successfully."}

            response = client.post("/api/auth/change-password", json={
                "current_password": "password123",
                "new_password": "password456",
                "confirm_new_password": "password456"
            }, headers={"Authorization": "Bearer token"})

            assert response.status_code == 200
            assert response.json()["message"] == "Password updated successfully."
            mock_change_password.assert_called_once_with(
                email="test@test.com",
                user_id="u1",
                current_password="password123",
                new_password="password456"
            )
        finally:
            app.dependency_overrides.pop(get_current_onboarded_user, None)

    @patch("app.api.v1.auth_routes.request_password_reset")
    def test_forgot_password_route(self, mock_forgot_password):
        mock_forgot_password.return_value = {"message": "Password reset email sent."}

        response = client.post("/api/auth/forgot-password", json={
            "email": "test@test.com"
        })

        assert response.status_code == 200
        assert response.json()["message"] == "Password reset email sent."
        mock_forgot_password.assert_called_once_with("test@test.com")

    @patch("app.api.v1.auth_routes.get_mfa_status")
    @patch("app.api.v1.auth_routes.supabase")
    def test_get_auth_me_route_includes_username(self, mock_sb, mock_mfa):
        class MockUser:
            id = "u1"
            email = "test@test.com"

        from app.core.dependencies import get_current_user
        app.dependency_overrides[get_current_user] = lambda: MockUser()

        try:
            chain = MagicMock()
            mock_sb.table.return_value = chain
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.single.return_value = chain
            chain.execute.return_value = MagicMock(data={"username": "alice_42", "role": "user"})
            mock_mfa.return_value = {
                "role": "user",
                "is_admin": False,
                "has_mfa_linked": False,
                "is_verified": True,
                "factor_id": None,
            }

            response = client.get("/api/auth/me", headers={"Authorization": "Bearer token"})
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == "u1"
            assert data["email"] == "test@test.com"
            assert data["username"] == "alice_42"
            assert data["is_admin"] is False
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    @patch("app.api.v1.auth_routes.get_mfa_status")
    @patch("app.api.v1.auth_routes.supabase")
    def test_get_auth_me_returns_admin_mfa_flags(self, mock_sb, mock_mfa):
        class MockAdmin:
            id = "admin-1"
            email = "admin@example.com"

        from app.core.dependencies import get_current_user
        app.dependency_overrides[get_current_user] = lambda: MockAdmin()

        try:
            chain = MagicMock()
            mock_sb.table.return_value = chain
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.single.return_value = chain
            chain.execute.return_value = MagicMock(data={"username": "admin", "role": "administrator"})
            mock_mfa.return_value = {
                "role": "administrator",
                "is_admin": True,
                "has_mfa_linked": True,
                "is_verified": False,
                "factor_id": "factor-1",
            }

            response = client.get("/api/auth/me", headers={"Authorization": "Bearer token"})
            assert response.status_code == 200
            data = response.json()
            assert data["is_admin"] is True
            assert data["has_mfa_linked"] is True
            assert data["is_verified"] is False
            assert data["factor_id"] == "factor-1"
            assert data["role"] == "administrator"
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    @patch("app.api.v1.auth_routes.login_with_google_id_token")
    def test_google_login_route_returns_admin_session(self, mock_google):
        mock_google.return_value = {
            "access_token": "supa-tok",
            "refresh_token": "refresh-tok",
            "token_type": "bearer",
            "role": "administrator",
            "is_admin": True,
            "has_mfa_linked": True,
            "is_verified": False,
            "factor_id": "factor-1",
        }

        response = client.post("/api/auth/google", json={"id_token": "google-id-token"})
        assert response.status_code == 200
        data = response.json()
        assert data["access_token"] == "supa-tok"
        assert data["is_admin"] is True
        assert data["is_verified"] is False
        mock_google.assert_called_once_with(
            id_token="google-id-token",
            nonce=None,
            access_token=None,
        )

    @patch("app.api.v1.auth_routes.build_auth_session_response")
    def test_session_route_returns_login_payload(self, mock_build):
        class MockAdmin:
            id = "admin-1"
            email = "admin@example.com"

        from app.core.dependencies import get_current_user
        app.dependency_overrides[get_current_user] = lambda: MockAdmin()
        try:
            mock_build.return_value = {
                "access_token": "tok",
                "token_type": "bearer",
                "role": "administrator",
                "is_admin": True,
                "has_mfa_linked": True,
                "is_verified": False,
                "factor_id": "factor-1",
            }
            response = client.get("/api/auth/session", headers={"Authorization": "Bearer tok"})
            assert response.status_code == 200
            assert response.json()["is_admin"] is True
            mock_build.assert_called_once_with("admin-1", {"access_token": "tok"})
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    def test_register_route_refuses_missing_username(self):
        payload = {
            "email": "test@test.com",
            "password": "password123",
            "invite_code": "ABCD-EFGH",
            "full_name": "Test User",
            "dob": "1990-01-01",
            "gender": "male",
            "interests": ["coding"]
        }
        response = client.post("/api/auth/register", json=payload)
        assert response.status_code == 400
        assert "username is required" in response.json()["detail"].lower()

    def test_register_route_refuses_spaces_only_full_name(self):
        payload = {
            "email": "test@test.com",
            "password": "password123",
            "invite_code": "ABCD-EFGH",
            "username": "testuser",
            "full_name": "   ",
            "dob": "1990-01-01",
            "gender": "male",
            "interests": ["coding"]
        }
        response = client.post("/api/auth/register", json=payload)
        assert response.status_code in (400, 422)
