from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.core.dependencies import require_admin
from app.services.registration_invite_service import (
    format_invite_code,
    hash_invite_code,
    normalize_invite_code,
    require_registration_invite,
    send_registration_invite,
)

client = TestClient(app)


def _invite_row(email="invitee@test.com", code="ABCD2345", expires_in_hours=24):
    return {
        "id": 11,
        "email": email,
        "code_hash": hash_invite_code(code),
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=expires_in_hours)).isoformat(),
        "used_at": None,
    }


class TestInviteCodeHelpers:
    def test_normalize_strips_dashes_and_case(self):
        assert normalize_invite_code("ab-cd 23-45") == "ABCD2345"
        assert format_invite_code("abcd2345") == "ABCD-2345"


class TestRequireRegistrationInvite:
    @patch("app.services.registration_invite_service.supabase")
    def test_accepts_matching_unused_code(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.is_.return_value = chain
        chain.order.return_value = chain
        chain.limit.return_value = chain
        chain.execute.return_value = MagicMock(data=[_invite_row()])

        row = require_registration_invite("Invitee@test.com", "abcd-2345")
        assert row["id"] == 11

    @patch("app.services.registration_invite_service.supabase")
    def test_rejects_wrong_code(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.is_.return_value = chain
        chain.order.return_value = chain
        chain.limit.return_value = chain
        chain.execute.return_value = MagicMock(data=[_invite_row()])

        try:
            require_registration_invite("invitee@test.com", "ZZZZ-9999")
            assert False, "expected HTTPException"
        except HTTPException as exc:
            assert exc.status_code == 400
            assert "invitation code" in exc.detail.lower()

    @patch("app.services.registration_invite_service.supabase")
    def test_rejects_expired_code(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.is_.return_value = chain
        chain.order.return_value = chain
        chain.limit.return_value = chain
        chain.execute.return_value = MagicMock(data=[_invite_row(expires_in_hours=-1)])

        try:
            require_registration_invite("invitee@test.com", "ABCD-2345")
            assert False, "expected HTTPException"
        except HTTPException as exc:
            assert exc.status_code == 400


class TestSendRegistrationInvite:
    @patch("app.services.audit_service.record_audit")
    @patch("app.services.email_service.send_email")
    @patch("app.services.registration_invite_service.supabase")
    def test_creates_invite_and_emails_code(self, mock_sb, mock_send, _audit):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.insert.return_value = chain
        chain.eq.return_value = chain
        chain.is_.return_value = chain
        chain.order.return_value = chain
        chain.limit.return_value = chain
        chain.execute.side_effect = [
            MagicMock(data=[]),
            MagicMock(data=[{"id": 22}]),
        ]

        result = send_registration_invite("admin-1", "New.User@test.com")

        assert result["email"] == "new.user@test.com"
        assert normalize_invite_code(result["code"])
        mock_send.assert_called_once()
        assert mock_send.call_args.args[0] == "new.user@test.com"
        insert_payload = chain.insert.call_args.args[0]
        assert insert_payload["email"] == "new.user@test.com"
        assert insert_payload["code_hash"] == hash_invite_code(result["code"])
        assert insert_payload["invited_by"] == "admin-1"


class TestInviteRoutes:
    def test_verify_invite_route(self):
        with patch(
            "app.services.registration_invite_service.verify_registration_invite",
            return_value={"valid": True, "email": "invitee@test.com"},
        ) as mock_verify:
            res = client.post("/api/auth/verify-invite", json={
                "email": "invitee@test.com",
                "invite_code": "ABCD-2345",
            })
        assert res.status_code == 200
        assert res.json()["valid"] is True
        mock_verify.assert_called_once()

    def test_register_refuses_missing_invite_code(self):
        res = client.post("/api/auth/register", json={
            "email": "test@test.com",
            "password": "password123",
            "username": "testuser",
            "full_name": "Test User",
            "dob": "1990-01-01",
            "gender": "male",
            "interests": ["coding"],
        })
        assert res.status_code == 422

    def test_admin_can_send_registration_invite(self):
        app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id="admin-1")
        try:
            with patch(
                "app.api.v1.admin_routes.send_registration_invite",
                return_value={
                    "email": "invitee@test.com",
                    "code": "ABCD-2345",
                    "expires_at": "2026-11-01T00:00:00+00:00",
                    "message": "Invitation email sent. The invited person must enter this code to register.",
                },
            ) as mock_send:
                res = client.post("/api/admin/invite_user/invitee@test.com")
                slashed = client.post("/api/admin/invite_user/invitee@test.com/")
            assert res.status_code == 200
            assert slashed.status_code == 200
            assert res.json()["code"] == "ABCD-2345"
            assert mock_send.call_count == 2
            assert mock_send.call_args_list[0].kwargs["email"] == "invitee@test.com"
        finally:
            app.dependency_overrides.pop(require_admin, None)

    def test_invite_user_refuses_invalid_email(self):
        app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id="admin-1")
        try:
            res = client.post("/api/admin/invite_user/not-an-email")
            assert res.status_code == 422
        finally:
            app.dependency_overrides.pop(require_admin, None)
