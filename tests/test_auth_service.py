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
        user.identities = ["identity"]
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

        select_chain = MagicMock()
        select_chain.select.return_value = select_chain
        select_chain.eq.return_value = select_chain
        select_chain.execute.return_value = MagicMock(data=[])

        update_chain = MagicMock()
        update_chain.update.return_value = update_chain
        update_chain.eq.return_value = update_chain
        update_chain.execute.return_value = MagicMock(data=[{"id": "uid-1"}])

        mock_sb.table.side_effect = [select_chain, update_chain]

        from app.services.auth_service import register_user
        result = register_user("a@b.com", "pass", "2000-01-01", "M", ["sports"], full_name="John Doe", username="john")

        assert result["access_token"] == "tok-abc"
        assert result["user_id"] == "uid-1"

    @patch("app.services.auth_service.supabase")
    def test_register_converts_capital_username_to_lowercase(self, mock_sb):
        auth_resp = self._make_auth_response()
        mock_sb.auth.sign_up.return_value = auth_resp

        select_chain = MagicMock()
        select_chain.select.return_value = select_chain
        select_chain.eq.return_value = select_chain
        select_chain.execute.return_value = MagicMock(data=[])

        update_chain = MagicMock()
        update_chain.update.return_value = update_chain
        update_chain.eq.return_value = update_chain
        update_chain.execute.return_value = MagicMock(data=[{"id": "uid-1"}])

        mock_sb.table.side_effect = [select_chain, update_chain]

        from app.services.auth_service import register_user
        result = register_user("a@b.com", "pass", "2000-01-01", "M", ["sports"], full_name="John Doe", username="John")

        # Check options sent to Supabase auth sign_up
        sign_up_args = mock_sb.auth.sign_up.call_args[0][0]
        assert sign_up_args["options"]["data"]["username"] == "john"
        # Check data sent to profile update
        update_args = update_chain.update.call_args[0][0]
        assert update_args["username"] == "john"
        assert update_args["full_name"] == "John Doe"

    @patch("app.services.auth_service.supabase")
    def test_register_no_session_returns_confirm_message(self, mock_sb):
        auth_resp = self._make_auth_response(with_session=False)
        mock_sb.auth.sign_up.return_value = auth_resp

        select_chain = MagicMock()
        select_chain.select.return_value = select_chain
        select_chain.eq.return_value = select_chain
        select_chain.execute.return_value = MagicMock(data=[])

        update_chain = MagicMock()
        update_chain.update.return_value = update_chain
        update_chain.eq.return_value = update_chain
        update_chain.execute.return_value = MagicMock(data=[])

        mock_sb.table.side_effect = [select_chain, update_chain]

        from app.services.auth_service import register_user
        result = register_user("a@b.com", "pass", "2000-01-01", "M", ["sports"], full_name="John Doe", username="john")

        assert "confirm email" in result["message"].lower()

    @patch("app.services.auth_service.supabase")
    def test_register_no_user_raises_400(self, mock_sb):
        resp = MagicMock()
        resp.user = None
        mock_sb.auth.sign_up.return_value = resp

        select_chain = MagicMock()
        select_chain.select.return_value = select_chain
        select_chain.eq.return_value = select_chain
        select_chain.execute.return_value = MagicMock(data=[])
        mock_sb.table.return_value = select_chain

        from app.services.auth_service import register_user
        with pytest.raises(HTTPException) as exc:
            register_user("a@b.com", "pass", "2000-01-01", "M", [], full_name="John Doe", username="john")
        assert exc.value.status_code == 400

    @patch("app.services.auth_service.supabase")
    def test_register_auth_api_error_raises_400(self, mock_sb):
        from gotrue.errors import AuthApiError
        mock_sb.auth.sign_up.side_effect = AuthApiError("email taken", status=400)

        select_chain = MagicMock()
        select_chain.select.return_value = select_chain
        select_chain.eq.return_value = select_chain
        select_chain.execute.return_value = MagicMock(data=[])
        mock_sb.table.return_value = select_chain

        from app.services.auth_service import register_user
        with pytest.raises(HTTPException) as exc:
            register_user("dup@b.com", "pass", "2000-01-01", "M", [], full_name="John Doe", username="john")
        assert exc.value.status_code == 400
        assert "Auth Error" in exc.value.detail

    @patch("app.services.auth_service.supabase")
    def test_register_age_check_raises_400(self, mock_sb):
        from postgrest.exceptions import APIError
        mock_sb.auth.sign_up.side_effect = APIError({"message": "age_18_or_older constraint"})

        select_chain = MagicMock()
        select_chain.select.return_value = select_chain
        select_chain.eq.return_value = select_chain
        select_chain.execute.return_value = MagicMock(data=[])
        mock_sb.table.return_value = select_chain

        from app.services.auth_service import register_user
        with pytest.raises(HTTPException) as exc:
            register_user("young@b.com", "pass", "2010-01-01", "M", [], full_name="John Doe", username="john")
        assert exc.value.status_code == 400
        assert "18 or older" in exc.value.detail

    @patch("app.services.auth_service.supabase")
    def test_register_existing_user_raises_409(self, mock_sb):
        resp = MagicMock()
        resp.user = MagicMock()
        resp.user.identities = []  # Empty identities indicates user already exists
        mock_sb.auth.sign_up.return_value = resp

        select_chain = MagicMock()
        select_chain.select.return_value = select_chain
        select_chain.eq.return_value = select_chain
        select_chain.execute.return_value = MagicMock(data=[])
        mock_sb.table.return_value = select_chain

        from app.services.auth_service import register_user
        with pytest.raises(HTTPException) as exc:
            register_user("existing@b.com", "pass", "2000-01-01", "M", [], full_name="John Doe", username="john")
        assert exc.value.status_code == 409
        assert "User already exists" in exc.value.detail
        assert "email address" in exc.value.detail.lower()
        assert "unavailable" in exc.value.detail.lower()

    @patch("app.services.auth_service.supabase")
    def test_register_taken_username_raises_409(self, mock_sb):
        select_chain = MagicMock()
        select_chain.select.return_value = select_chain
        select_chain.eq.return_value = select_chain
        select_chain.execute.return_value = MagicMock(data=[{"id": "other-user"}])
        mock_sb.table.return_value = select_chain

        from app.services.auth_service import register_user
        with pytest.raises(HTTPException) as exc:
            register_user("a@b.com", "pass", "2000-01-01", "M", [], full_name="John Doe", username="taken_user")
        assert exc.value.status_code == 409
        assert "username" in exc.value.detail.lower()
        assert "unavailable" in exc.value.detail.lower()

    @patch("app.services.auth_service.supabase")
    def test_register_taken_username_case_insensitive_raises_409(self, mock_sb):
        select_chain = MagicMock()
        select_chain.select.return_value = select_chain
        select_chain.eq.return_value = select_chain
        select_chain.execute.return_value = MagicMock(data=[{"id": "other-user"}])
        mock_sb.table.return_value = select_chain

        from app.services.auth_service import register_user
        with pytest.raises(HTTPException) as exc:
            register_user("a@b.com", "pass", "2000-01-01", "M", [], full_name="John Doe", username="Taken_User")
        assert exc.value.status_code == 409
        assert "username" in exc.value.detail.lower()
        assert "unavailable" in exc.value.detail.lower()
        select_chain.eq.assert_called_once_with("username", "taken_user")

    def test_register_without_username_raises_400(self):
        from app.services.auth_service import register_user
        with pytest.raises(HTTPException) as exc:
            register_user("a@b.com", "pass", "2000-01-01", "M", [], full_name="John Doe", username=None)
        assert exc.value.status_code == 400
        assert "username is required" in exc.value.detail.lower()

    def test_register_empty_username_raises_400(self):
        from app.services.auth_service import register_user
        with pytest.raises(HTTPException) as exc:
            register_user("a@b.com", "pass", "2000-01-01", "M", [], full_name="John Doe", username="   ")
        assert exc.value.status_code == 400

    @pytest.mark.parametrize("invalid_username", [
        "ab",                   # Too short (2 chars)
        "a" * 21,               # Too long (21 chars)
        "john doe",             # Contains spaces
        "john-doe",             # Hyphen not allowed
        "john@doe",             # @ not allowed
        "john!42",              # ! not allowed
    ])
    def test_register_invalid_username_format_raises_400(self, invalid_username):
        from app.services.auth_service import register_user
        with pytest.raises(HTTPException) as exc:
            register_user("a@b.com", "pass", "2000-01-01", "M", [], full_name="John Doe", username=invalid_username)
        assert exc.value.status_code == 400
        assert "username must be between 3 and 20" in exc.value.detail.lower()

    def test_register_without_full_name_raises_400(self):
        from app.services.auth_service import register_user
        with pytest.raises(HTTPException) as exc:
            register_user("a@b.com", "pass", "2000-01-01", "M", [], full_name=None, username="john")
        assert exc.value.status_code == 400
        assert "full name is required" in exc.value.detail.lower()

    def test_register_spaces_only_full_name_raises_400(self):
        from app.services.auth_service import register_user
        with pytest.raises(HTTPException) as exc:
            register_user("a@b.com", "pass", "2000-01-01", "M", [], full_name="     ", username="john")
        assert exc.value.status_code == 400

    @pytest.mark.parametrize("invalid_name", [
        "Jo",                   # Too short once stripped (<3 chars)
        "A" * 51,               # Too long once stripped (>50 chars)
        "12345",                # Numbers
        "John 123",             # Contains numbers
        "John_Smith",           # Underscore is not common name punctuation
        "John@Doe",             # Disallowed symbol
        "...",                  # Punctuation only, no letters
    ])
    def test_register_invalid_full_name_format_raises_400(self, invalid_name):
        from app.services.auth_service import register_user
        with pytest.raises(HTTPException) as exc:
            register_user("a@b.com", "pass", "2000-01-01", "M", [], full_name=invalid_name, username="john")
        assert exc.value.status_code == 400



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