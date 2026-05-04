import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from app.main import app

client = TestClient(app)

class TestAuthRoutes:
    @patch("app.api.v1.auth_routes.register_user")
    def test_register_route(self, mock_register):
        mock_register.return_value = {"access_token": "token", "user_id": "u1"}
        
        payload = {
            "email": "test@test.com",
            "password": "password123",
            "dob": "1990-01-01",
            "gender": "male",
            "interests": ["coding"]
        }
        
        response = client.post("/api/auth/register", json=payload)
        
        assert response.status_code == 200
        assert response.json() == {"access_token": "token", "user_id": "u1"}
        mock_register.assert_called_once()

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