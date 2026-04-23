import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timezone

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