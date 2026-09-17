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
            username="testuser"
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
                username="Alice",
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
            
        def override_get_current_user():
            return MockUser()
            
        from app.core.dependencies import get_current_user
        app.dependency_overrides[get_current_user] = override_get_current_user
        
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
            app.dependency_overrides.pop(get_current_user, None)

    @patch("app.api.v1.auth_routes.request_password_reset")
    def test_forgot_password_route(self, mock_forgot_password):
        mock_forgot_password.return_value = {"message": "Password reset email sent."}
        
        response = client.post("/api/auth/forgot-password", json={
            "email": "test@test.com"
        })
        
        assert response.status_code == 200
        assert response.json()["message"] == "Password reset email sent."
        mock_forgot_password.assert_called_once_with("test@test.com")

    @patch("app.api.v1.auth_routes.supabase")
    def test_get_auth_me_route_includes_username(self, mock_sb):
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
            chain.execute.return_value = MagicMock(data={"username": "alice_42"})

            response = client.get("/api/auth/me", headers={"Authorization": "Bearer token"})
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == "u1"
            assert data["email"] == "test@test.com"
            assert data["username"] == "alice_42"
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    def test_register_route_refuses_missing_username(self):
        payload = {
            "email": "test@test.com",
            "password": "password123",
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
            "username": "testuser",
            "full_name": "   ",
            "dob": "1990-01-01",
            "gender": "male",
            "interests": ["coding"]
        }
        response = client.post("/api/auth/register", json=payload)
        assert response.status_code == 400
        assert "full name is required" in response.json()["detail"].lower()