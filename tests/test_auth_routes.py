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