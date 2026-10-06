import base64
import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app
from app.core.dependencies import get_current_user, require_admin

client = TestClient(app)


def _create_jwt(payload: dict) -> str:
    """Helper to create an unverified base64-encoded JWT structure for tests."""
    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).decode().rstrip("=")
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    signature = "signature"
    return f"{header}.{body}.{signature}"


class TestMFAAuthentication:
    """Tests covering ticket #150: Administrator Sign-in Verification and Server-side Role Checks."""

    # 1. Login behavior for normal user vs administrator
    @patch("app.services.auth_service.supabase")
    def test_login_normal_user_unaltered(self, mock_sb):
        """Normal users sign in without MFA and get is_admin=False, is_verified=True."""
        auth_resp = MagicMock()
        auth_resp.session.access_token = _create_jwt({"sub": "user-1", "aal": "aal1"})
        auth_resp.user.id = "user-1"
        mock_sb.auth.sign_in_with_password.return_value = auth_resp

        # Mock profile query returning role 'user'
        profile_chain = MagicMock()
        profile_chain.select.return_value = profile_chain
        profile_chain.eq.return_value = profile_chain
        profile_chain.single.return_value = profile_chain
        profile_chain.execute.return_value = MagicMock(data={"role": "user"})
        mock_sb.table.return_value = profile_chain

        from app.services.auth_service import login_user
        res = login_user("user@example.com", "secret123")
        assert res["role"] == "user"
        assert res["is_admin"] is False
        assert res["has_mfa_linked"] is False
        assert res["is_verified"] is True
        assert "access_token" in res

    @patch("app.services.auth_service.get_user_factors")
    @patch("app.services.auth_service.supabase")
    def test_login_admin_first_time_unlinked(self, mock_sb, mock_factors):
        """First time administrator sign-in: has_mfa_linked=False, is_verified=False."""
        auth_resp = MagicMock()
        auth_resp.session.access_token = _create_jwt({"sub": "admin-1", "aal": "aal1"})
        auth_resp.user.id = "admin-1"
        mock_sb.auth.sign_in_with_password.return_value = auth_resp

        # Mock profile returning role 'administrator'
        profile_chain = MagicMock()
        profile_chain.select.return_value = profile_chain
        profile_chain.eq.return_value = profile_chain
        profile_chain.single.return_value = profile_chain
        profile_chain.execute.return_value = MagicMock(data={"role": "administrator"})
        mock_sb.table.return_value = profile_chain

        # No verified factors
        mock_factors.return_value = []

        from app.services.auth_service import login_user
        res = login_user("admin@example.com", "secret123")
        assert res["role"] == "administrator"
        assert res["is_admin"] is True
        assert res["has_mfa_linked"] is False
        assert res["is_verified"] is False

    @patch("app.services.auth_service.get_user_factors")
    @patch("app.services.auth_service.supabase")
    def test_login_admin_second_time_linked(self, mock_sb, mock_factors):
        """Subsequent administrator sign-in: has_mfa_linked=True, is_verified=False, includes factor_id."""
        auth_resp = MagicMock()
        auth_resp.session.access_token = _create_jwt({"sub": "admin-1", "aal": "aal1"})
        auth_resp.user.id = "admin-1"
        mock_sb.auth.sign_in_with_password.return_value = auth_resp

        profile_chain = MagicMock()
        profile_chain.select.return_value = profile_chain
        profile_chain.eq.return_value = profile_chain
        profile_chain.single.return_value = profile_chain
        profile_chain.execute.return_value = MagicMock(data={"role": "administrator"})
        mock_sb.table.return_value = profile_chain

        # Verified factor present
        mock_factor = MagicMock()
        mock_factor.factor_type = "totp"
        mock_factor.status = "verified"
        mock_factor.id = "factor-xyz"
        mock_factors.return_value = [mock_factor]

        from app.services.auth_service import login_user
        res = login_user("admin@example.com", "secret123")
        assert res["role"] == "administrator"
        assert res["is_admin"] is True
        assert res["has_mfa_linked"] is True
        assert res["is_verified"] is False
        assert res["factor_id"] == "factor-xyz"

    # 2. MFA Enroll Endpoint
    @patch("app.services.auth_service.supabase")
    def test_mfa_enroll_refused_for_non_admin(self, mock_sb):
        """Only administrator accounts can link an app; requests from other accounts are refused (403)."""
        class MockUser:
            id = "user-regular"
            email = "user@example.com"

        app.dependency_overrides[get_current_user] = lambda: MockUser()
        try:
            profile_chain = MagicMock()
            profile_chain.select.return_value = profile_chain
            profile_chain.eq.return_value = profile_chain
            profile_chain.single.return_value = profile_chain
            profile_chain.execute.return_value = MagicMock(data={"role": "user"})
            mock_sb.table.return_value = profile_chain

            response = client.post(
                "/api/auth/mfa/enroll",
                headers={"Authorization": "Bearer token-123"}
            )
            assert response.status_code == 403
            assert "only administrator accounts" in response.json()["detail"].lower()
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    @patch("httpx.post")
    @patch("app.services.auth_service.supabase")
    def test_mfa_enroll_success_for_admin(self, mock_sb, mock_http_post):
        """Administrator accounts can link an app and receive QR code details."""
        class MockAdmin:
            id = "admin-1"
            email = "admin@example.com"

        app.dependency_overrides[get_current_user] = lambda: MockAdmin()
        try:
            profile_chain = MagicMock()
            profile_chain.select.return_value = profile_chain
            profile_chain.eq.return_value = profile_chain
            profile_chain.single.return_value = profile_chain
            profile_chain.execute.return_value = MagicMock(data={"role": "administrator"})
            mock_sb.table.return_value = profile_chain

            mock_http_resp = MagicMock()
            mock_http_resp.status_code = 200
            mock_http_resp.json.return_value = {
                "id": "factor-123",
                "type": "totp",
                "totp": {
                    "qr_code": "<svg>qrcode</svg>",
                    "secret": "JBSWY3DPEHPK3PXP",
                    "uri": "otpauth://totp/EventGit:admin@example.com?secret=JBSWY3DPEHPK3PXP"
                }
            }
            mock_http_post.return_value = mock_http_resp

            response = client.post(
                "/api/auth/mfa/enroll",
                headers={"Authorization": "Bearer valid-token"}
            )
            assert response.status_code == 200
            data = response.json()
            assert data["factor_id"] == "factor-123"
            assert data["totp"]["secret"] == "JBSWY3DPEHPK3PXP"
            assert data["totp"]["qr_code"].startswith("data:image/svg+xml;utf-8,")
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    # 3. MFA Verify Endpoint
    @patch("app.services.auth_service.supabase")
    def test_mfa_verify_refused_for_non_admin(self, mock_sb):
        """Non-admin accounts attempting to verify MFA are refused (403)."""
        class MockUser:
            id = "user-1"
            email = "user@example.com"

        app.dependency_overrides[get_current_user] = lambda: MockUser()
        try:
            profile_chain = MagicMock()
            profile_chain.select.return_value = profile_chain
            profile_chain.eq.return_value = profile_chain
            profile_chain.single.return_value = profile_chain
            profile_chain.execute.return_value = MagicMock(data={"role": "user"})
            mock_sb.table.return_value = profile_chain

            response = client.post(
                "/api/auth/mfa/verify",
                json={"code": "123456", "factor_id": "factor-1"},
                headers={"Authorization": "Bearer token"}
            )
            assert response.status_code == 403
            assert "only administrator accounts" in response.json()["detail"].lower()
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    @patch("httpx.post")
    @patch("app.services.auth_service.supabase")
    def test_mfa_verify_refuses_wrong_code(self, mock_sb, mock_http_post):
        """A wrong code is refused with status 400 and a descriptive message."""
        class MockAdmin:
            id = "admin-1"
            email = "admin@example.com"

        app.dependency_overrides[get_current_user] = lambda: MockAdmin()
        try:
            profile_chain = MagicMock()
            profile_chain.select.return_value = profile_chain
            profile_chain.eq.return_value = profile_chain
            profile_chain.single.return_value = profile_chain
            profile_chain.execute.return_value = MagicMock(data={"role": "administrator"})
            mock_sb.table.return_value = profile_chain

            # First post is challenge, second is verify
            challenge_resp = MagicMock()
            challenge_resp.status_code = 200
            challenge_resp.json.return_value = {"id": "challenge-1"}

            verify_resp = MagicMock()
            verify_resp.status_code = 400
            verify_resp.text = "Invalid TOTP code"

            mock_http_post.side_effect = [challenge_resp, verify_resp]

            response = client.post(
                "/api/auth/mfa/verify",
                json={"code": "000000", "factor_id": "factor-1"},
                headers={"Authorization": "Bearer token"}
            )
            assert response.status_code == 400
            assert "invalid verification code" in response.json()["detail"].lower()
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    @patch("httpx.post")
    @patch("app.services.auth_service.supabase")
    def test_mfa_verify_accepts_correct_code_and_upgrades_token(self, mock_sb, mock_http_post):
        """Correct code verifies sign-in and returns upgraded session token with is_verified=True."""
        class MockAdmin:
            id = "admin-1"
            email = "admin@example.com"

        app.dependency_overrides[get_current_user] = lambda: MockAdmin()
        try:
            profile_chain = MagicMock()
            profile_chain.select.return_value = profile_chain
            profile_chain.eq.return_value = profile_chain
            profile_chain.single.return_value = profile_chain
            profile_chain.execute.return_value = MagicMock(data={"role": "administrator"})
            mock_sb.table.return_value = profile_chain

            challenge_resp = MagicMock()
            challenge_resp.status_code = 200
            challenge_resp.json.return_value = {"id": "challenge-1"}

            upgraded_token = _create_jwt({"sub": "admin-1", "aal": "aal2"})
            verify_resp = MagicMock()
            verify_resp.status_code = 200
            verify_resp.json.return_value = {
                "access_token": upgraded_token,
                "token_type": "bearer"
            }

            mock_http_post.side_effect = [challenge_resp, verify_resp]

            response = client.post(
                "/api/auth/mfa/verify",
                json={"code": "654321", "factor_id": "factor-1"},
                headers={"Authorization": "Bearer token"}
            )
            assert response.status_code == 200
            data = response.json()
            assert data["is_verified"] is True
            assert data["access_token"] == upgraded_token
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    # 4. Administrative Endpoints Server-side Protection (require_admin)
    @patch("app.core.dependencies.supabase")
    def test_require_admin_refuses_non_admin(self, mock_sb):
        """Administrative endpoint refuses non-admin accounts even with valid token (403)."""
        valid_user = MagicMock()
        valid_user.id = "user-regular"
        mock_sb.auth.get_user.return_value = MagicMock(user=valid_user)

        # Profile returns role 'user'
        profile_chain = MagicMock()
        profile_chain.select.return_value = profile_chain
        profile_chain.eq.return_value = profile_chain
        profile_chain.single.return_value = profile_chain
        profile_chain.execute.return_value = MagicMock(data={"role": "user"})
        mock_sb.table.return_value = profile_chain

        aal2_token = _create_jwt({"sub": "user-regular", "aal": "aal2"})
        response = client.get("/api/admin/verify", headers={"Authorization": f"Bearer {aal2_token}"})
        assert response.status_code == 403
        assert "administrative privileges required" in response.json()["detail"].lower()

    @patch("app.core.dependencies.supabase")
    def test_require_admin_refuses_unverified_admin_aal1(self, mock_sb):
        """Administrative endpoint refuses administrator whose current sign-in is not MFA verified (aal1)."""
        admin_user = MagicMock()
        admin_user.id = "admin-1"
        mock_sb.auth.get_user.return_value = MagicMock(user=admin_user)

        profile_chain = MagicMock()
        profile_chain.select.return_value = profile_chain
        profile_chain.eq.return_value = profile_chain
        profile_chain.single.return_value = profile_chain
        profile_chain.execute.return_value = MagicMock(data={"role": "administrator"})
        mock_sb.table.return_value = profile_chain

        aal1_token = _create_jwt({"sub": "admin-1", "aal": "aal1"})
        response = client.get("/api/admin/verify", headers={"Authorization": f"Bearer {aal1_token}"})
        assert response.status_code == 403
        assert "administrator sign-in verification required" in response.json()["detail"].lower()

    @patch("app.core.dependencies.supabase")
    def test_require_admin_refuses_forged_token(self, mock_sb):
        """Administrative endpoint refuses forged token failing Supabase authenticity check (401)."""
        # supabase.auth.get_user throws on invalid/forged signature
        mock_sb.auth.get_user.side_effect = Exception("Invalid signature")

        response = client.get("/api/admin/verify", headers={"Authorization": "Bearer forged-token"})
        assert response.status_code == 401
        assert "invalid or expired token" in response.json()["detail"].lower()

    @patch("app.core.dependencies.supabase")
    def test_require_admin_accepts_verified_admin_aal2(self, mock_sb):
        """Administrative endpoint grants access to verified administrator with aal2 token."""
        admin_user = MagicMock()
        admin_user.id = "admin-1"
        mock_sb.auth.get_user.return_value = MagicMock(user=admin_user)

        profile_chain = MagicMock()
        profile_chain.select.return_value = profile_chain
        profile_chain.eq.return_value = profile_chain
        profile_chain.single.return_value = profile_chain
        profile_chain.execute.return_value = MagicMock(data={"role": "administrator"})
        mock_sb.table.return_value = profile_chain

        aal2_token = _create_jwt({"sub": "admin-1", "aal": "aal2"})
        response = client.get("/api/admin/verify", headers={"Authorization": f"Bearer {aal2_token}"})
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert response.json()["admin_id"] == "admin-1"
