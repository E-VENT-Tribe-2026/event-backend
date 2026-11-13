"""Regression tests for change_password / POST /api/auth/change-password (ticket #273).

The current password must be verified before the admin update runs.
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from gotrue.errors import AuthApiError

from app.core.dependencies import get_current_onboarded_user
from app.core.limiter import limiter
from app.main import app
from app.services.auth_service import change_password

INCORRECT = "Incorrect current password."
UPDATE_FAILED = "Password update failed. Please try again."
SUCCESS = {"message": "Password updated successfully."}

client = TestClient(app)


def _invalid_credentials():
    return AuthApiError("Invalid login credentials", 400)


class TestChangePasswordService:
    @patch("supabase.create_client")
    @patch("app.services.auth_service.supabase")
    def test_invalid_login_credentials_raises_401_without_update(self, mock_sb, mock_create_client):
        mock_sb.auth.sign_in_with_password.side_effect = _invalid_credentials()

        with pytest.raises(HTTPException) as exc:
            change_password("test@test.com", "u1", "wrong", "newpass")

        assert exc.value.status_code == 401
        assert exc.value.detail == INCORRECT
        mock_create_client.assert_not_called()
        mock_create_client.return_value.auth.admin.update_user_by_id.assert_not_called()

    @patch("supabase.create_client")
    @patch("app.services.auth_service.supabase")
    def test_none_session_raises_401_without_update(self, mock_sb, mock_create_client):
        mock_sb.auth.sign_in_with_password.return_value = MagicMock(session=None)

        with pytest.raises(HTTPException) as exc:
            change_password("test@test.com", "u1", "wrong", "newpass")

        assert exc.value.status_code == 401
        assert exc.value.detail == INCORRECT
        mock_create_client.assert_not_called()

    @patch("supabase.create_client")
    @patch("app.services.auth_service.supabase")
    def test_update_happens_only_after_verification(self, mock_sb, mock_create_client):
        manager = MagicMock()
        manager.attach_mock(mock_sb.auth.sign_in_with_password, "sign_in")
        admin = mock_create_client.return_value
        manager.attach_mock(admin.auth.admin.update_user_by_id, "update")
        mock_sb.auth.sign_in_with_password.return_value = MagicMock(session="valid_session")

        result = change_password("test@test.com", "u1", "correct", "newpass")

        assert result == SUCCESS
        names = [c[0] for c in manager.mock_calls]
        assert names == ["sign_in", "update"]
        manager.sign_in.assert_called_once_with({"email": "test@test.com", "password": "correct"})
        manager.update.assert_called_once_with("u1", {"password": "newpass"})
        mock_sb.auth.sign_out.assert_called_once_with()

    @patch("supabase.create_client")
    @patch("app.services.auth_service.supabase")
    def test_other_auth_api_error_raises_400_without_update(self, mock_sb, mock_create_client):
        mock_sb.auth.sign_in_with_password.side_effect = AuthApiError("Service unavailable", 500)

        with pytest.raises(HTTPException) as exc:
            change_password("test@test.com", "u1", "correct", "newpass")

        assert exc.value.status_code == 400
        assert exc.value.detail == UPDATE_FAILED
        mock_create_client.assert_not_called()

    @patch("supabase.create_client")
    @patch("app.services.auth_service.supabase")
    def test_non_auth_exception_propagates_without_update(self, mock_sb, mock_create_client):
        mock_sb.auth.sign_in_with_password.side_effect = RuntimeError("boom")

        with pytest.raises(RuntimeError):
            change_password("test@test.com", "u1", "correct", "newpass")

        mock_create_client.assert_not_called()


class _MockUser:
    id = "u1"
    email = "test@test.com"


class TestChangePasswordRoute:
    @pytest.fixture(autouse=True)
    def _setup(self):
        limiter.reset()
        app.dependency_overrides[get_current_onboarded_user] = lambda: _MockUser()
        yield
        app.dependency_overrides.pop(get_current_onboarded_user, None)
        limiter.reset()

    def _post(self, body):
        return client.post("/api/auth/change-password", json=body,
                           headers={"Authorization": "Bearer token"})

    @patch("supabase.create_client")
    @patch("app.services.auth_service.supabase")
    def test_wrong_current_password_returns_401_without_update(self, mock_sb, mock_create_client):
        mock_sb.auth.sign_in_with_password.side_effect = _invalid_credentials()

        response = self._post({
            "current_password": "wrong",
            "new_password": "password456",
            "confirm_new_password": "password456",
        })

        assert response.status_code == 401
        assert response.json()["detail"] == INCORRECT
        mock_create_client.return_value.auth.admin.update_user_by_id.assert_not_called()

    @patch("supabase.create_client")
    @patch("app.services.auth_service.supabase")
    def test_correct_current_password_returns_200_and_updates_once(self, mock_sb, mock_create_client):
        mock_sb.auth.sign_in_with_password.return_value = MagicMock(session="valid_session")

        response = self._post({
            "current_password": "password123",
            "new_password": "password456",
            "confirm_new_password": "password456",
        })

        assert response.status_code == 200
        assert response.json() == SUCCESS
        mock_create_client.return_value.auth.admin.update_user_by_id.assert_called_once_with(
            "u1", {"password": "password456"}
        )

    @patch("supabase.create_client")
    @patch("app.services.auth_service.supabase")
    def test_old_confirm_password_field_name_returns_422(self, mock_sb, mock_create_client):
        response = self._post({
            "current_password": "password123",
            "new_password": "password456",
            "confirm_password": "password456",
        })

        assert response.status_code == 422
        mock_sb.auth.sign_in_with_password.assert_not_called()
        mock_create_client.assert_not_called()
