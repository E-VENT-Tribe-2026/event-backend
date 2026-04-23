import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException
from app.services.saved_event_service import save_event, remove_saved_event, get_saved_events


class TestSaveEvent:
    @patch("app.services.saved_event_service.supabase")
    def test_save_success(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.insert.return_value = chain
        chain.eq.return_value = chain
        # No existing save
        chain.execute.side_effect = [
            MagicMock(data=[]),
            MagicMock(data=[{"user_id": "u1", "event_id": "e1"}]),
        ]

        result = save_event("u1", "e1")

        assert result["message"] == "Event saved"

    @patch("app.services.saved_event_service.supabase")
    def test_save_duplicate_raises_400(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[{"id": "existing"}])

        with pytest.raises(HTTPException) as exc:
            save_event("u1", "e1")
        assert exc.value.status_code == 400
        assert "already saved" in exc.value.detail.lower()


class TestRemoveSavedEvent:
    @patch("app.services.saved_event_service.supabase")
    def test_remove_returns_message(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.delete.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[])

        result = remove_saved_event("u1", "e1")

        assert result["message"] == "Removed from saved events"
        chain.delete.assert_called_once()

    @patch("app.services.saved_event_service.supabase")
    def test_remove_filters_by_user_and_event(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.delete.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[])

        remove_saved_event("u1", "e1")

        eq_calls = [str(c) for c in chain.eq.call_args_list]
        assert any("u1" in c for c in eq_calls)
        assert any("e1" in c for c in eq_calls)


class TestGetSavedEvents:
    @patch("app.services.saved_event_service.supabase")
    def test_returns_event_objects(self, mock_sb):
        rows = [
            {"events": {"id": "e1", "title": "Party"}},
            {"events": {"id": "e2", "title": "Concert"}},
        ]
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=rows)

        result = get_saved_events("u1")

        assert len(result) == 2
        assert result[0] == {"id": "e1", "title": "Party"}
        assert result[1] == {"id": "e2", "title": "Concert"}

    @patch("app.services.saved_event_service.supabase")
    def test_returns_empty_list(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[])

        result = get_saved_events("u1")

        assert result == []