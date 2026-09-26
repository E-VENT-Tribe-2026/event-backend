import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException

from tests._supabase_mock import make_table_router


# ────────────────────────────────────────────────────────────────────────────
# get_event_messages
# ────────────────────────────────────────────────────────────────────────────

class TestGetEventMessagesAccess:
    def test_raises_403_when_not_participant(self):
        mock_sb, chains = make_table_router()
        chains["event_participants"].execute.return_value = MagicMock(data=[])

        with patch("app.services.chat_service.supabase", mock_sb), \
             patch("app.services.chat_service.get_user_summaries") as mock_summaries:
            from app.services.chat_service import get_event_messages
            with pytest.raises(HTTPException) as exc:
                get_event_messages("u1", "e1")
            assert exc.value.status_code == 403
            mock_summaries.assert_not_called()


class TestGetEventMessagesEmpty:
    def test_no_messages_returns_empty_data_and_skips_summaries(self):
        mock_sb, chains = make_table_router()
        chains["event_participants"].execute.return_value = MagicMock(data=[{"user_id": "u1"}])
        chains["event_chats"].execute.return_value = MagicMock(data=[])

        with patch("app.services.chat_service.supabase", mock_sb), \
             patch("app.services.chat_service.get_user_summaries") as mock_summaries:
            from app.services.chat_service import get_event_messages
            result = get_event_messages("u1", "e1", page=1, limit=50)

            assert result == {"event_id": "e1", "page": 1, "limit": 50, "data": []}
            mock_summaries.assert_not_called()


class TestGetEventMessagesEnriched:
    def _setup(self, mock_sb, chains, messages, organizer_id="org1"):
        chains["event_participants"].execute.return_value = MagicMock(data=[{"user_id": "u1"}])
        chains["event_chats"].execute.return_value = MagicMock(data=messages)
        chains["events"].execute.return_value = MagicMock(data={"created_by": organizer_id})

    def test_summaries_called_once_with_unique_non_null_sender_ids(self):
        mock_sb, chains = make_table_router()
        messages = [
            {"id": 1, "sender_id": "org1", "content": "hi", "type": "chat"},
            {"id": 2, "sender_id": "u2", "content": "yo", "type": "chat"},
            {"id": 3, "sender_id": None, "content": "sys note", "type": "notification"},
        ]
        self._setup(mock_sb, chains, messages)

        summaries = {
            "org1": {"id": "org1", "username": "org_user", "full_name": "Org Anizer",
                      "display_name": "org_user", "avatar_kind": "icon", "icon_id": "icon_fox", "avatar_url": None},
            "u2": {"id": "u2", "username": None, "full_name": "User Two",
                    "display_name": "User Two", "avatar_kind": "icon", "icon_id": None, "avatar_url": None},
        }

        with patch("app.services.chat_service.supabase", mock_sb), \
             patch("app.services.chat_service.get_user_summaries", return_value=summaries) as mock_summaries:
            from app.services.chat_service import get_event_messages
            result = get_event_messages("u1", "e1")

            mock_summaries.assert_called_once()
            called_ids = mock_summaries.call_args[0][0]
            assert set(called_ids) == {"org1", "u2"}

            data = result["data"]
            organizer_msg = next(m for m in data if m["id"] == 1)
            participant_msg = next(m for m in data if m["id"] == 2)
            system_msg = next(m for m in data if m["id"] == 3)

            assert organizer_msg["sender"] == summaries["org1"]
            assert organizer_msg["sender_name"] == "Org Anizer"
            assert organizer_msg["sender_role"] == "organizer"

            assert participant_msg["sender"] == summaries["u2"]
            assert participant_msg["sender_name"] == "User Two"
            assert participant_msg["sender_role"] == "participant"

            assert system_msg["sender"] is None
            assert system_msg["sender_name"] == "System"
            assert system_msg["sender_role"] == "system"

    def test_sender_with_missing_profile_uses_stub_and_unknown_name(self):
        mock_sb, chains = make_table_router()
        messages = [
            {"id": 1, "sender_id": "ghost", "content": "hi", "type": "chat"},
        ]
        self._setup(mock_sb, chains, messages)

        stub = {"id": "ghost", "username": None, "full_name": None, "display_name": None,
                "avatar_kind": "icon", "icon_id": None, "avatar_url": None}

        with patch("app.services.chat_service.supabase", mock_sb), \
             patch("app.services.chat_service.get_user_summaries", return_value={"ghost": stub}):
            from app.services.chat_service import get_event_messages
            result = get_event_messages("u1", "e1")

            msg = result["data"][0]
            assert msg["sender"] == stub
            assert msg["sender_name"] == "Unknown"
            assert msg["sender_role"] == "participant"


    def test_all_system_messages_skips_summaries(self):
        mock_sb, chains = make_table_router()
        messages = [
            {"id": 1, "sender_id": None, "content": "sys note 1", "type": "notification"},
            {"id": 2, "sender_id": None, "content": "sys note 2", "type": "notification"},
        ]
        self._setup(mock_sb, chains, messages)

        with patch("app.services.chat_service.supabase", mock_sb), \
             patch("app.services.chat_service.get_user_summaries") as mock_summaries:
            from app.services.chat_service import get_event_messages
            result = get_event_messages("u1", "e1")

            mock_summaries.assert_not_called()
            for msg in result["data"]:
                assert msg["sender"] is None
                assert msg["sender_name"] == "System"
                assert msg["sender_role"] == "system"

    def test_same_sender_gets_independent_sender_dicts(self):
        mock_sb, chains = make_table_router()
        messages = [
            {"id": 1, "sender_id": "u2", "content": "hi", "type": "chat"},
            {"id": 2, "sender_id": "u2", "content": "yo", "type": "chat"},
        ]
        self._setup(mock_sb, chains, messages)

        summaries = {
            "u2": {"id": "u2", "username": None, "full_name": "User Two",
                    "display_name": "User Two", "avatar_kind": "icon", "icon_id": None, "avatar_url": None},
        }

        with patch("app.services.chat_service.supabase", mock_sb), \
             patch("app.services.chat_service.get_user_summaries", return_value=summaries):
            from app.services.chat_service import get_event_messages
            result = get_event_messages("u1", "e1")

            data = result["data"]
            first_msg = next(m for m in data if m["id"] == 1)
            second_msg = next(m for m in data if m["id"] == 2)

            assert first_msg["sender"] == second_msg["sender"]
            assert first_msg["sender"] is not second_msg["sender"]


# ────────────────────────────────────────────────────────────────────────────
# send_message
# ────────────────────────────────────────────────────────────────────────────

class TestSendMessage:
    def test_enriches_inserted_row_with_sender_summary(self):
        mock_sb, chains = make_table_router()
        chains["event_participants"].execute.return_value = MagicMock(data=[{"user_id": "u1"}])
        chains["event_chats"].execute.return_value = MagicMock(data=[
            {"id": 10, "event_id": "e1", "sender_id": "u1", "content": "hello", "type": "chat"}
        ])
        chains["events"].execute.return_value = MagicMock(data={"created_by": "org1"})

        summary = {"id": "u1", "username": "john_42", "full_name": "John Doe",
                   "display_name": "john_42", "avatar_kind": "icon", "icon_id": "icon_fox", "avatar_url": None}

        with patch("app.services.chat_service.supabase", mock_sb), \
             patch("app.services.chat_service.get_user_summaries", return_value={"u1": summary}) as mock_summaries:
            from app.services.chat_service import send_message
            result = send_message("u1", "e1", "hello")

            mock_summaries.assert_called_once()
            called_ids = mock_summaries.call_args[0][0]
            assert set(called_ids) == {"u1"}

            assert result["sender"] == summary
            assert result["sender_name"] == "John Doe"
            assert result["sender_role"] == "participant"


# ────────────────────────────────────────────────────────────────────────────
# update_message
# ────────────────────────────────────────────────────────────────────────────

class TestGetEventMessagesOrganizerLookupFailure:
    def test_unresolvable_organizer_falls_back_to_participant_role_and_single_lookup(self):
        mock_sb, chains = make_table_router()
        chains["event_participants"].execute.return_value = MagicMock(data=[{"user_id": "u1"}])
        messages = [
            {"id": 1, "sender_id": "u1", "content": "hi", "type": "chat"},
            {"id": 2, "sender_id": "u2", "content": "yo", "type": "chat"},
            {"id": 3, "sender_id": "u3", "content": "sup", "type": "chat"},
        ]
        chains["event_chats"].execute.return_value = MagicMock(data=messages)
        chains["events"].execute.return_value = MagicMock(data={"created_by": None})

        summaries = {
            "u1": {"id": "u1", "username": "u1", "full_name": "User One",
                    "display_name": "u1", "avatar_kind": "icon", "icon_id": None, "avatar_url": None},
            "u2": {"id": "u2", "username": "u2", "full_name": "User Two",
                    "display_name": "u2", "avatar_kind": "icon", "icon_id": None, "avatar_url": None},
            "u3": {"id": "u3", "username": "u3", "full_name": "User Three",
                    "display_name": "u3", "avatar_kind": "icon", "icon_id": None, "avatar_url": None},
        }

        with patch("app.services.chat_service.supabase", mock_sb), \
             patch("app.services.chat_service.get_user_summaries", return_value=summaries):
            from app.services.chat_service import get_event_messages
            result = get_event_messages("u1", "e1")

            assert chains["events"].execute.call_count == 1
            for msg in result["data"]:
                assert msg["sender_role"] == "participant"


# ────────────────────────────────────────────────────────────────────────────
# update_message / send_message: guarded organizer lookup (F-007)
# ────────────────────────────────────────────────────────────────────────────

class TestUpdateMessageOrganizerLookupFailure:
    def test_lookup_failure_still_returns_enriched_message_and_logs_error(self, caplog):
        mock_sb, chains = make_table_router()
        chains["event_chats"].execute.side_effect = [
            MagicMock(data={"id": 5, "event_id": "e1", "sender_id": "u1", "content": "old"}),
            MagicMock(data=[{"id": 5, "event_id": "e1", "sender_id": "u1", "content": "new"}]),
        ]
        chains["events"].execute.side_effect = Exception("db down")

        summary = {"id": "u1", "username": "john_42", "full_name": "John Doe",
                   "display_name": "john_42", "avatar_kind": "icon", "icon_id": "icon_fox", "avatar_url": None}

        with patch("app.services.chat_service.supabase", mock_sb), \
             patch("app.services.chat_service.get_user_summaries", return_value={"u1": summary}), \
             caplog.at_level("ERROR", logger="app.services.chat_service"):
            from app.services.chat_service import update_message
            result = update_message("u1", 5, "new")

            assert result["content"] == "new"
            assert result["sender"] == summary
            assert result["sender_role"] == "participant"
            assert any(record.levelname == "ERROR" for record in caplog.records)


class TestSendMessageOrganizerLookupFailure:
    def test_lookup_failure_still_returns_enriched_message(self):
        mock_sb, chains = make_table_router()
        chains["event_participants"].execute.return_value = MagicMock(data=[{"user_id": "u1"}])
        chains["event_chats"].execute.return_value = MagicMock(data=[
            {"id": 10, "event_id": "e1", "sender_id": "u1", "content": "hello", "type": "chat"}
        ])
        chains["events"].execute.side_effect = Exception("db down")

        summary = {"id": "u1", "username": "john_42", "full_name": "John Doe",
                   "display_name": "john_42", "avatar_kind": "icon", "icon_id": "icon_fox", "avatar_url": None}

        with patch("app.services.chat_service.supabase", mock_sb), \
             patch("app.services.chat_service.get_user_summaries", return_value={"u1": summary}):
            from app.services.chat_service import send_message
            result = send_message("u1", "e1", "hello")

            assert result["sender"] == summary
            assert result["sender_role"] == "participant"


class TestUpdateMessage:
    def test_updated_message_gains_sender_fields(self):
        mock_sb, chains = make_table_router()
        chains["event_chats"].execute.side_effect = [
            MagicMock(data={"id": 5, "event_id": "e1", "sender_id": "u1", "content": "old"}),
            MagicMock(data=[{"id": 5, "event_id": "e1", "sender_id": "u1", "content": "new"}]),
        ]
        chains["events"].execute.return_value = MagicMock(data={"created_by": "org1"})

        summary = {"id": "u1", "username": "john_42", "full_name": "John Doe",
                   "display_name": "john_42", "avatar_kind": "icon", "icon_id": "icon_fox", "avatar_url": None}

        with patch("app.services.chat_service.supabase", mock_sb), \
             patch("app.services.chat_service.get_user_summaries", return_value={"u1": summary}):
            from app.services.chat_service import update_message
            result = update_message("u1", 5, "new")

            assert result["content"] == "new"
            assert result["sender"] == summary
            assert result["sender_name"] == "John Doe"
            assert result["sender_role"] == "participant"

    def test_editing_someone_elses_message_still_raises_403(self):
        mock_sb, chains = make_table_router()
        chains["event_chats"].execute.return_value = MagicMock(
            data={"id": 5, "event_id": "e1", "sender_id": "someone_else", "content": "old"}
        )

        with patch("app.services.chat_service.supabase", mock_sb):
            from app.services.chat_service import update_message
            with pytest.raises(HTTPException) as exc:
                update_message("u1", 5, "new")
            assert exc.value.status_code == 403
