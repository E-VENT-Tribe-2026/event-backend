import pytest
from unittest.mock import MagicMock, patch, call


class TestCreateNotification:
    @patch("app.services.notification_service.supabase")
    def test_creates_notification_when_no_duplicate(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.insert.return_value = chain
        # No existing record
        chain.execute.return_value = MagicMock(data=[])

        from app.services.notification_service import create_notification
        create_notification("u1", "e1", "event_updated", "hello")

        # insert was called once
        chain.insert.assert_called_once()

    @patch("app.services.notification_service.supabase")
    def test_skips_duplicate_notification(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.order.return_value = chain  # <-- ADD THIS
        chain.limit.return_value = chain  # <-- ADD THIS
        chain.insert.return_value = chain

        from datetime import datetime, timezone

        # Existing record present with a timestamp from exactly right now
        mock_time = datetime.now(timezone.utc).isoformat()
        chain.execute.return_value = MagicMock(data=[{"id": 99, "created_at": mock_time}])

        from app.services.notification_service import create_notification
        create_notification("u1", "e1", "event_updated", "hello")

        chain.insert.assert_not_called()

    @patch("app.services.notification_service.supabase")
    def test_notification_payload_fields(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.insert.return_value = chain
        chain.execute.return_value = MagicMock(data=[])

        from app.services.notification_service import create_notification
        create_notification("u2", "e2", "event_cancelled", "Cancelled")

        args = chain.insert.call_args[0][0]
        assert args["user_id"] == "u2"
        assert args["event_id"] == "e2"
        assert args["type"] == "event_cancelled"
        assert args["message"] == "Cancelled"
        assert args["is_read"] is False
        assert "created_at" in args


class TestGetNotifications:
    @patch("app.services.notification_service.supabase")
    def test_returns_paginated_data(self, mock_sb):
        rows = [{"id": 1}, {"id": 2}]
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.order.return_value = chain
        chain.range.return_value = chain
        chain.execute.return_value = MagicMock(data=rows)

        from app.services.notification_service import get_notifications
        result = get_notifications("u1", page=2, limit=2)

        assert result["page"] == 2
        assert result["limit"] == 2
        assert result["data"] == rows
        # range should be called with (2, 3) for page=2, limit=2
        chain.range.assert_called_once_with(2, 3)

    @patch("app.services.notification_service.supabase")
    def test_default_pagination(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.order.return_value = chain
        chain.range.return_value = chain
        chain.execute.return_value = MagicMock(data=[])

        from app.services.notification_service import get_notifications
        result = get_notifications("u1")

        assert result["page"] == 1
        assert result["limit"] == 10
        chain.range.assert_called_once_with(0, 9)


class TestMarkAsRead:
    @patch("app.services.notification_service.supabase")
    def test_mark_as_read_calls_update(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.update.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[{"id": 1, "is_read": True}])

        from app.services.notification_service import mark_as_read
        mark_as_read(1, "u1")

        chain.update.assert_called_once_with({"is_read": True})
        # Two .eq() calls: one for id, one for user_id
        assert chain.eq.call_count == 2


class TestMarkAllAsRead:
    @patch("app.services.notification_service.supabase")
    def test_mark_all_as_read_calls_update_with_filters(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.update.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[])

        from app.services.notification_service import mark_all_as_read
        mark_all_as_read("u1")

        chain.update.assert_called_once_with({"is_read": True})
        # Two .eq() calls: one for user_id, one for is_read=False
        assert chain.eq.call_count == 2
        
        # Verify specific filter calls
        calls = [
            call("user_id", "u1"),
            call("is_read", False)
        ]
        chain.eq.assert_has_calls(calls, any_order=True)


class TestDeleteSelected:
    @patch("app.services.notification_service.supabase")
    def test_delete_selected_calls_delete_with_filters(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.delete.return_value = chain
        chain.eq.return_value = chain
        chain.in_.return_value = chain
        chain.execute.return_value = MagicMock(data=[])

        from app.services.notification_service import delete_selected_notifications
        delete_selected_notifications([1, 2, 3], "u1")

        chain.delete.assert_called_once()
        chain.eq.assert_called_once_with("user_id", "u1")
        chain.in_.assert_called_once_with("id", [1, 2, 3])

def _dedupe_chain(existing=None):
    chain = MagicMock()
    for name in ("select", "eq", "is_", "order", "limit", "insert"):
        getattr(chain, name).return_value = chain
    chain.execute.return_value = MagicMock(data=existing or [])
    return chain


class TestCreateNotificationRelatedUser:
    @patch("app.services.notification_service.supabase")
    def test_null_event_id_dedupe_uses_is_null(self, mock_sb):
        chain = _dedupe_chain()
        mock_sb.table.return_value = chain

        from app.services.notification_service import create_notification
        create_notification("u1", None, "friend_request_received", "hi")

        chain.is_.assert_called_once_with("event_id", "null")
        for c in chain.eq.call_args_list:
            assert c != call("event_id", None)
            assert c.args[0] != "event_id"

    @patch("app.services.notification_service.supabase")
    def test_event_id_dedupe_uses_eq(self, mock_sb):
        chain = _dedupe_chain()
        mock_sb.table.return_value = chain

        from app.services.notification_service import create_notification
        create_notification("u1", "e1", "event_updated", "hi")

        chain.eq.assert_any_call("event_id", "e1")
        chain.is_.assert_not_called()

    @patch("app.services.notification_service.supabase")
    def test_related_user_id_in_payload_and_dedupe(self, mock_sb):
        chain = _dedupe_chain()
        mock_sb.table.return_value = chain

        from app.services.notification_service import create_notification
        create_notification("u1", None, "friend_request_received", "hi", related_user_id="u9")

        payload = chain.insert.call_args[0][0]
        assert payload["related_user_id"] == "u9"
        chain.eq.assert_any_call("related_user_id", "u9")

    @patch("app.services.notification_service.supabase")
    def test_no_related_user_id_key_when_not_given(self, mock_sb):
        chain = _dedupe_chain()
        mock_sb.table.return_value = chain

        from app.services.notification_service import create_notification
        create_notification("u1", "e1", "event_updated", "hi")

        payload = chain.insert.call_args[0][0]
        assert "related_user_id" not in payload
        for c in chain.eq.call_args_list:
            assert c.args[0] != "related_user_id"


class TestDeleteNotificationsFor:
    @patch("app.services.notification_service.supabase")
    def test_deletes_with_filters_and_returns_data(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.delete.return_value = chain
        chain.eq.return_value = chain
        rows = [{"id": 1}]
        chain.execute.return_value = MagicMock(data=rows)

        from app.services.notification_service import delete_notifications_for
        result = delete_notifications_for("u1", "friend_request_received", "u2")

        mock_sb.table.assert_called_with("notifications")
        chain.delete.assert_called_once()
        assert chain.eq.call_args_list == [
            call("user_id", "u1"),
            call("type", "friend_request_received"),
            call("related_user_id", "u2"),
        ]
        assert result == rows

    @patch("app.services.notification_service.supabase")
    def test_returns_empty_list_when_data_none(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.delete.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=None)

        from app.services.notification_service import delete_notifications_for
        assert delete_notifications_for("u1", "t", "u2") == []


class TestGetNotificationsRelatedUser:
    def _chain(self, rows):
        chain = MagicMock()
        for name in ("select", "eq", "order", "range"):
            getattr(chain, name).return_value = chain
        chain.execute.return_value = MagicMock(data=rows)
        return chain

    @patch("app.services.notification_service.get_user_summaries")
    @patch("app.services.notification_service.supabase")
    def test_attaches_related_user_with_single_lookup(self, mock_sb, mock_summaries):
        rows = [
            {"id": 1, "related_user_id": "u2"},
            {"id": 2, "related_user_id": None},
            {"id": 3, "related_user_id": "u3"},
            {"id": 4},
        ]
        mock_sb.table.return_value = self._chain(rows)
        mock_summaries.return_value = {"u2": {"id": "u2"}, "u3": {"id": "u3"}}

        from app.services.notification_service import get_notifications
        result = get_notifications("u1", page=1, limit=10)

        mock_summaries.assert_called_once()
        assert set(mock_summaries.call_args[0][0]) == {"u2", "u3"}
        by_id = {r["id"]: r for r in result["data"]}
        assert by_id[1]["related_user"] == {"id": "u2"}
        assert by_id[3]["related_user"] == {"id": "u3"}
        assert by_id[2]["related_user"] is None
        assert by_id[4]["related_user"] is None
        assert set(result.keys()) == {"page", "limit", "data"}

    @patch("app.services.notification_service.get_user_summaries")
    @patch("app.services.notification_service.supabase")
    def test_no_lookup_when_no_related_users(self, mock_sb, mock_summaries):
        rows = [{"id": 1, "related_user_id": None}, {"id": 2}]
        mock_sb.table.return_value = self._chain(rows)

        from app.services.notification_service import get_notifications
        result = get_notifications("u1")

        mock_summaries.assert_not_called()
        assert all(r["related_user"] is None for r in result["data"])
        assert result["page"] == 1
        assert result["limit"] == 10
