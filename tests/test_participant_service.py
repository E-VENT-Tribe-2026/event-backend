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


class TestJoinSideEffects:
    @patch("app.services.participant_service._get_user_email", return_value=None)
    @patch("app.services.participant_service.post_system_notification")
    @patch("app.services.participant_service.create_notification")
    @patch("app.services.participant_service.get_username", return_value="john")
    def test_join_side_effects(self, mock_get_username, mock_create_notification, mock_post_system, mock_get_email):
        from app.services.participant_service import _join_side_effects

        event = {"id": "e1", "title": "Tech Conference 2026", "created_by": "org1"}
        _join_side_effects("u1", "e1", event)

        mock_get_username.assert_called_once_with("u1")
        mock_post_system.assert_called_once_with("e1", "👋 john has joined this chat")
        mock_create_notification.assert_any_call("org1", "e1", "user_joined", "john joined your event 'Tech Conference 2026'")
        mock_create_notification.assert_any_call("u1", "e1", "joined_event", "You have joined 'Tech Conference 2026'")


class TestLeaveSideEffects:
    @patch("app.services.participant_service._get_user_email", return_value=None)
    @patch("app.services.participant_service.post_system_notification")
    @patch("app.services.participant_service.create_notification")
    @patch("app.services.participant_service.get_username", return_value="john")
    def test_leave_side_effects(self, mock_get_username, mock_create_notification, mock_post_system, mock_get_email):
        from app.services.participant_service import _leave_side_effects

        event = {"id": "e1", "title": "Tech Conference 2026", "created_by": "org1"}
        _leave_side_effects("u1", "e1", event)

        mock_get_username.assert_called_once_with("u1")
        mock_post_system.assert_called_once_with("e1", "👋 john has left this chat")
        mock_create_notification.assert_any_call("org1", "e1", "user_left", "john left your event 'Tech Conference 2026'")
        mock_create_notification.assert_any_call("u1", "e1", "left_event", "You have left 'Tech Conference 2026'")


class TestRemoveSideEffects:
    @patch("app.services.participant_service._get_user_email", return_value=None)
    @patch("app.services.participant_service.create_notification")
    @patch("app.services.participant_service.get_username", return_value="alice")
    def test_remove_side_effects(self, mock_get_username, mock_create_notification, mock_get_email):
        from app.services.participant_service import _remove_side_effects

        event = {"id": "e1", "title": "Tech Conference 2026", "created_by": "org1"}
        _remove_side_effects("org1", "e1", "p1", event)

        mock_get_username.assert_called_once_with("org1")
        mock_create_notification.assert_called_once_with(
            "p1", "e1", "removed_from_event", "You have been removed from 'Tech Conference 2026' by alice."
        )


# ────────────────────────────────────────────────────────────────────────────
# Ticket #122 P1: participant list carries username / full name / avatar summary
# ────────────────────────────────────────────────────────────────────────────

class TestGetEventParticipantsUserSummary:
    @patch("app.services.participant_service.supabase")
    def test_single_query_select_includes_embed_columns(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[])

        from app.services.participant_service import get_event_participants
        get_event_participants("e1")

        assert mock_sb.table.call_count == 1
        mock_sb.table.assert_called_once_with("event_participants")
        select_arg = chain.select.call_args[0][0]
        assert "user_id" in select_arg
        assert "status" in select_arg
        assert "profiles(" in select_arg
        assert "username" in select_arg
        assert "full_name" in select_arg
        assert "avatar_url" in select_arg
        assert "avatar_kind" in select_arg
        assert "icon_id" in select_arg
        chain.eq.assert_called_once_with("event_id", "e1")

    @patch("app.services.participant_service.supabase")
    def test_user_with_username_and_icon(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[
            {
                "user_id": "u1",
                "status": "going",
                "profiles": {
                    "username": "john_42",
                    "full_name": "John Doe",
                    "avatar_url": None,
                    "avatar_kind": "icon",
                    "icon_id": "icon_fox",
                },
            }
        ])

        from app.services.participant_service import get_event_participants
        result = get_event_participants("e1")

        row = result[0]
        assert row["user_id"] == "u1"
        assert row["status"] == "going"
        assert row["profiles"] == {"full_name": "John Doe", "avatar_url": None}
        assert row["user"]["id"] == "u1"
        assert row["user"]["username"] == "john_42"
        assert row["user"]["display_name"] == "john_42"
        assert row["user"]["avatar_kind"] == "icon"
        assert row["user"]["icon_id"] == "icon_fox"

    @patch("app.services.participant_service.supabase")
    def test_user_with_photo(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[
            {
                "user_id": "u2",
                "status": "going",
                "profiles": {
                    "username": "jane99",
                    "full_name": "Jane Roe",
                    "avatar_url": "https://cdn.example.com/p.png",
                    "avatar_kind": "photo",
                    "icon_id": None,
                },
            }
        ])

        from app.services.participant_service import get_event_participants
        result = get_event_participants("e1")

        row = result[0]
        assert row["profiles"] == {"full_name": "Jane Roe", "avatar_url": "https://cdn.example.com/p.png"}
        assert row["user"]["avatar_kind"] == "photo"
        assert row["user"]["avatar_url"] == "https://cdn.example.com/p.png"

    @patch("app.services.participant_service.supabase")
    def test_legacy_account_without_username_falls_back_to_full_name(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[
            {
                "user_id": "u3",
                "status": "interested",
                "profiles": {
                    "username": None,
                    "full_name": "Legacy Larry",
                    "avatar_url": None,
                    "avatar_kind": None,
                    "icon_id": None,
                },
            }
        ])

        from app.services.participant_service import get_event_participants
        result = get_event_participants("e1")

        row = result[0]
        assert row["user"]["username"] is None
        assert row["user"]["display_name"] == "Legacy Larry"
        assert row["user"]["avatar_kind"] == "icon"

    @patch("app.services.participant_service.supabase")
    def test_missing_profile_yields_stub_user_and_none_profiles(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[
            {
                "user_id": "u4",
                "status": "going",
                "profiles": None,
            }
        ])

        from app.services.participant_service import get_event_participants
        from app.services.profile_service import build_user_summary
        result = get_event_participants("e1")

        row = result[0]
        assert row["profiles"] is None
        assert row["user"] == build_user_summary(None, "u4")

    @patch("app.services.participant_service.supabase")
    def test_list_shaped_embed_uses_first_element_and_returns_trimmed_object(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[
            {
                "user_id": "u5",
                "status": "going",
                "profiles": [
                    {
                        "username": "jill5",
                        "full_name": "Jill Five",
                        "avatar_url": "https://cdn.example.com/j.png",
                        "avatar_kind": "photo",
                        "icon_id": None,
                    }
                ],
            }
        ])

        from app.services.participant_service import get_event_participants
        result = get_event_participants("e1")

        row = result[0]
        assert row["user"]["id"] == "u5"
        assert row["user"]["username"] == "jill5"
        assert row["user"]["avatar_kind"] == "photo"
        assert row["profiles"] == {"full_name": "Jill Five", "avatar_url": "https://cdn.example.com/j.png"}

    @patch("app.services.participant_service.supabase")
    def test_empty_list_embed_yields_stub_user_and_none_profiles(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[
            {
                "user_id": "u6",
                "status": "going",
                "profiles": [],
            }
        ])

        from app.services.participant_service import get_event_participants
        from app.services.profile_service import build_user_summary
        result = get_event_participants("e1")

        row = result[0]
        assert row["user"] == build_user_summary(None, "u6")
        assert row["profiles"] is None

    @patch("app.services.participant_service.supabase")
    def test_list_containing_none_yields_stub_user_and_none_profiles(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[
            {
                "user_id": "u7",
                "status": "going",
                "profiles": [None],
            }
        ])

        from app.services.participant_service import get_event_participants
        from app.services.profile_service import build_user_summary
        result = get_event_participants("e1")

        row = result[0]
        assert row["user"] == build_user_summary(None, "u7")
        assert row["profiles"] is None
