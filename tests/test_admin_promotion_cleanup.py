"""Ticket #229: making a user an administrator must not report success when required cleanup failed."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import require_admin
from app.main import app

client = TestClient(app)

TARGET = "44444444-4444-4444-8444-444444444444"


class MockAdminUser:
    id = "22222222-2222-2222-2222-222222222222"
    email = "admin@example.com"


def _mock_supabase(mock_sb, calls, failing_table=None):
    """Target is a regular user. Deleting from `failing_table` raises; records updates and inserts."""
    def table_router(table_name):
        chain = MagicMock()
        for method in ("select", "eq", "neq", "single", "in_"):
            getattr(chain, method).return_value = chain

        def delete():
            if table_name == failing_table:
                raise RuntimeError(f"cannot delete from {table_name}")
            return chain

        def update(payload):
            calls.append(("update", table_name, payload))
            return chain

        def insert(payload):
            calls.append(("insert", table_name, payload))
            return chain

        chain.delete.side_effect = delete
        chain.update.side_effect = update
        chain.insert.side_effect = insert
        if table_name == "profiles":
            chain.execute.return_value = MagicMock(data=[{"id": TARGET, "username": "bob", "role": "user"}])
        else:
            chain.execute.return_value = MagicMock(data=[])
        return chain

    mock_sb.table.side_effect = table_router
    mock_sb.rpc.return_value.execute.return_value = MagicMock(data=1)


class TestGrantAdminCleanupFailures:
    def setup_method(self):
        app.dependency_overrides[require_admin] = lambda: MockAdminUser()

    def teardown_method(self):
        app.dependency_overrides.pop(require_admin, None)

    @pytest.mark.parametrize("failing_table, summary_key", [
        ("friendships", "friendships_deleted"),
        ("friend_requests", "friend_requests_deleted"),
        ("user_blocks", "blocks_deleted"),
        ("saved_events", "saved_events_deleted"),
        ("notifications", "notifications_deleted"),
    ])
    @patch("app.services.admin_service.supabase")
    def test_failed_cleanup_does_not_grant_role(self, mock_sb, failing_table, summary_key):
        calls = []
        _mock_supabase(mock_sb, calls, failing_table=failing_table)

        res = client.post(f"/api/admin/users/{TARGET}/grant-admin")

        # Not reported as success, and the reason names the failed step.
        assert res.status_code == 500
        assert summary_key in res.json()["detail"]
        assert "not granted" in res.json()["detail"]

        # The account was not made an administrator.
        assert not any(c[0] == "update" and c[1] == "profiles" for c in calls)

        # The audit log tells the truth about what happened.
        logs = [c[2] for c in calls if c[0] == "insert" and c[1] == "logs"]
        assert len(logs) == 1
        assert logs[0]["type"] == "make_admin_failed"
        assert f"{summary_key}:False" in logs[0]["values"]
        assert "role_granted:False" in logs[0]["values"]

    @patch("app.services.admin_service.supabase")
    def test_full_success_reports_every_step_true(self, mock_sb):
        calls = []
        _mock_supabase(mock_sb, calls)

        res = client.post(f"/api/admin/users/{TARGET}/grant-admin")

        assert res.status_code == 200
        summary = res.json()["summary"]
        for key in ("friendships_deleted", "friend_requests_deleted", "blocks_deleted",
                    "saved_events_deleted", "notifications_deleted", "profile_purged"):
            assert summary[key] is True
        logs = [c[2] for c in calls if c[0] == "insert" and c[1] == "logs"]
        assert logs[-1]["type"] == "make_admin"
        assert "friendships_deleted:True" in logs[-1]["values"]
