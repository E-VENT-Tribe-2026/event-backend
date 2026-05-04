import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _mock_supabase():
    """Return a fully-stubbed supabase client."""
    sb = MagicMock()
    # Chain: .table().select().eq().execute() etc.
    chain = MagicMock()
    sb.table.return_value = chain
    chain.select.return_value = chain
    chain.insert.return_value = chain
    chain.update.return_value = chain
    chain.delete.return_value = chain
    chain.eq.return_value = chain
    chain.single.return_value = chain
    chain.execute.return_value = MagicMock(data=None)
    return sb


# ──────────────────────────────────────────────
# register_user
# ──────────────────────────────────────────────

class TestRegisterUser:
    def _make_auth_response(self, user_id="uid-1", with_session=True):
        user = MagicMock()
        user.id = user_id
        session = MagicMock()
        session.access_token = "tok-abc"
        resp = MagicMock()
        resp.user = user
        resp.session = session if with_session else None
        return resp

    @patch("app.services.auth_service.supabase")
    def test_register_success_returns_token(self, mock_sb):
        auth_resp = self._make_auth_response()
        mock_sb.auth.sign_up.return_value = auth_resp

        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.update.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[{"id": "uid-1"}])

        from app.services.auth_service import register_user
        result = register_user("a@b.com", "pass", "2000-01-01", "M", ["sports"])

        assert result["access_token"] == "tok-abc"
        assert result["user_id"] == "uid-1"

    @patch("app.services.auth_service.supabase")
    def test_register_no_session_returns_confirm_message(self, mock_sb):
        auth_resp = self._make_auth_response(with_session=False)
        mock_sb.auth.sign_up.return_value = auth_resp

        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.update.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[])

        from app.services.auth_service import register_user
        result = register_user("a@b.com", "pass", "2000-01-01", "M", ["sports"])

        assert "confirm email" in result["message"].lower()

    @patch("app.services.auth_service.supabase")
    def test_register_no_user_raises_400(self, mock_sb):
        resp = MagicMock()
        resp.user = None
        mock_sb.auth.sign_up.return_value = resp

        from app.services.auth_service import register_user
        with pytest.raises(HTTPException) as exc:
            register_user("a@b.com", "pass", "2000-01-01", "M", [])
        assert exc.value.status_code == 400

    @patch("app.services.auth_service.supabase")
    def test_register_auth_api_error_raises_400(self, mock_sb):
        from gotrue.errors import AuthApiError
        mock_sb.auth.sign_up.side_effect = AuthApiError("email taken", status=400)

        from app.services.auth_service import register_user
        with pytest.raises(HTTPException) as exc:
            register_user("dup@b.com", "pass", "2000-01-01", "M", [])
        assert exc.value.status_code == 400
        assert "Auth Error" in exc.value.detail

    @patch("app.services.auth_service.supabase")
    def test_register_age_check_raises_400(self, mock_sb):
        from openai import APIError
        mock_sb.auth.sign_up.side_effect = APIError(
            message="age_18_or_older constraint", request=MagicMock(), body={}
        )

        from app.services.auth_service import register_user
        with pytest.raises(HTTPException) as exc:
            register_user("young@b.com", "pass", "2010-01-01", "M", [])
        assert exc.value.status_code == 400
        assert "18 or older" in exc.value.detail


# ──────────────────────────────────────────────
# login_user
# ──────────────────────────────────────────────

class TestLoginUser:
    @patch("app.services.auth_service.supabase")
    def test_login_success(self, mock_sb):
        session = MagicMock()
        session.access_token = "tok-xyz"
        resp = MagicMock()
        resp.session = session
        mock_sb.auth.sign_in_with_password.return_value = resp

        from app.services.auth_service import login_user
        result = login_user("a@b.com", "pass")

        assert result["access_token"] == "tok-xyz"
        assert result["token_type"] == "bearer"

    @patch("app.services.auth_service.supabase")
    def test_login_no_session_raises_401(self, mock_sb):
        resp = MagicMock()
        resp.session = None
        mock_sb.auth.sign_in_with_password.return_value = resp

        from app.services.auth_service import login_user
        with pytest.raises(HTTPException) as exc:
            login_user("a@b.com", "wrong")
        assert exc.value.status_code == 401

# ──────────────────────────────────────────────
# change_password
# ──────────────────────────────────────────────

class TestChangePassword:
    def test_change_password_same_password_raises_400(self):
        from app.services.auth_service import change_password
        with pytest.raises(HTTPException) as exc:
            change_password("test@test.com", "u1", "samepass", "samepass")
        assert exc.value.status_code == 400
        assert "cannot be the same" in exc.value.detail.lower()

    @patch("app.services.auth_service.supabase")
    def test_change_password_invalid_current_password_raises_401(self, mock_sb):
        from app.services.auth_service import change_password
        mock_sb.auth.sign_in_with_password.return_value = MagicMock(session=None)
        
        with pytest.raises(HTTPException) as exc:
            change_password("test@test.com", "u1", "wrong", "newpass")
        assert exc.value.status_code == 401
        assert "incorrect current password" in exc.value.detail.lower()

    @patch("supabase.create_client")
    @patch("app.services.auth_service.supabase")
    def test_change_password_success(self, mock_sb, mock_create_client):
        from app.services.auth_service import change_password
        mock_sb.auth.sign_in_with_password.return_value = MagicMock(session="valid_session")
        
        mock_admin_client = MagicMock()
        mock_create_client.return_value = mock_admin_client
        
        result = change_password("test@test.com", "u1", "correct", "newpass")
        
        assert result["message"] == "Password updated successfully."
        mock_admin_client.auth.admin.update_user_by_id.assert_called_once_with(
            "u1",
            {"password": "newpass"}
        )