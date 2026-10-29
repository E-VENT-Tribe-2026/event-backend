"""Ticket #228: making a user an administrator must end their existing sessions."""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.core.dependencies import require_admin
from app.main import app

client = TestClient(app)

TARGET = "33333333-3333-4333-8333-333333333333"


class MockAdminUser:
    id = "22222222-2222-2222-2222-222222222222"
    email = "admin@example.com"


def _mock_supabase(mock_sb, calls):
    """Every table returns the target as a regular user; records which tables were updated or inserted."""
    def table_router(table_name):
        chain = MagicMock()
        for method in ("select", "eq", "neq", "single", "in_", "delete"):
            getattr(chain, method).return_value = chain

        def update(payload):
            calls.append(("update", table_name))
            return chain

        def insert(payload):
            calls.append(("insert", table_name))
            return chain

        chain.update.side_effect = update
        chain.insert.side_effect = insert
        if table_name == "profiles":
            chain.execute.return_value = MagicMock(data=[{"id": TARGET, "username": "alice", "role": "user"}])
        else:
            chain.execute.return_value = MagicMock(data=[])
        return chain

    mock_sb.table.side_effect = table_router


class TestGrantAdminRevokesSessions:
    def setup_method(self):
        app.dependency_overrides[require_admin] = lambda: MockAdminUser()

    def teardown_method(self):
        app.dependency_overrides.pop(require_admin, None)

    @patch("app.services.admin_service.supabase")
    def test_success_revokes_sessions_with_supported_function(self, mock_sb):
        calls = []
        _mock_supabase(mock_sb, calls)
        mock_sb.rpc.return_value.execute.return_value = MagicMock(data=2)

        with patch("requests.post") as old_logout:
            res = client.post(f"/api/admin/users/{TARGET}/grant-admin")

        assert res.status_code == 200
        assert res.json()["summary"]["sessions_revoked"] is True
        # Before changing anything, and again after the role change.
        assert mock_sb.rpc.call_count == 2
        for c in mock_sb.rpc.call_args_list:
            assert c.args == ("revoke_user_sessions", {"p_user_id": TARGET})
        # The unsupported /admin/users/{id}/logout route is no longer called.
        old_logout.assert_not_called()

    @patch("app.services.admin_service.supabase")
    def test_revoke_failure_before_changes_refuses_and_changes_nothing(self, mock_sb):
        calls = []
        _mock_supabase(mock_sb, calls)
        mock_sb.rpc.return_value.execute.side_effect = RuntimeError("function missing")

        res = client.post(f"/api/admin/users/{TARGET}/grant-admin")

        assert res.status_code == 500
        assert "not changed" in res.json()["detail"]
        assert ("update", "profiles") not in calls
        mock_sb.rpc.assert_called_once()

    @patch("app.services.admin_service.supabase")
    def test_revoke_failure_after_promotion_is_not_reported_as_success(self, mock_sb):
        calls = []
        _mock_supabase(mock_sb, calls)
        mock_sb.rpc.return_value.execute.side_effect = [MagicMock(data=1), RuntimeError("db down")]

        res = client.post(f"/api/admin/users/{TARGET}/grant-admin")

        assert res.status_code == 500
        assert "sessions could not be ended" in res.json()["detail"]
        # The promotion is still written to the audit log.
        assert ("insert", "logs") in calls