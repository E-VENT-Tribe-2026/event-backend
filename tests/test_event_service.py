import logging
import pytest
from unittest.mock import MagicMock, patch, call
from fastapi import HTTPException


# ──────────────────────────────────────────────
# validate_coordinates
# ──────────────────────────────────────────────

class TestValidateCoordinates:
    def test_valid_coordinates_pass(self):
        from app.services.event_service import validate_coordinates
        validate_coordinates(52.0, 13.0)  # should not raise

    def test_none_coordinates_pass(self):
        from app.services.event_service import validate_coordinates
        validate_coordinates(None, None)

    def test_invalid_latitude_raises_400(self):
        from app.services.event_service import validate_coordinates
        with pytest.raises(HTTPException) as exc:
            validate_coordinates(91.0, 0.0)
        assert exc.value.status_code == 400
        assert "latitude" in exc.value.detail.lower()

    def test_invalid_longitude_raises_400(self):
        from app.services.event_service import validate_coordinates
        with pytest.raises(HTTPException) as exc:
            validate_coordinates(0.0, 200.0)
        assert exc.value.status_code == 400
        assert "longitude" in exc.value.detail.lower()

    def test_non_numeric_raises_400(self):
        from app.services.event_service import validate_coordinates
        with pytest.raises(HTTPException) as exc:
            validate_coordinates("abc", "xyz")
        assert exc.value.status_code == 400


# ──────────────────────────────────────────────
# get_event
# ──────────────────────────────────────────────

class TestGetEvent:
    @patch("app.services.event_service.supabase")
    def test_returns_event(self, mock_sb):
        event = {"id": "e1", "title": "Party"}
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.single.return_value = chain
        chain.execute.return_value = MagicMock(data=event)

        from app.services.event_service import get_event
        assert get_event("e1") == event

    @patch("app.services.event_service.supabase")
    def test_raises_404_when_missing(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.single.return_value = chain
        chain.execute.return_value = MagicMock(data=None)

        from app.services.event_service import get_event
        with pytest.raises(HTTPException) as exc:
            get_event("ghost")
        assert exc.value.status_code == 404


# ──────────────────────────────────────────────
# create_event
# ──────────────────────────────────────────────

class TestCreateEvent:
    def _stub_chain(self, mock_sb, event_row):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.insert.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[event_row])
        return chain
    
    @patch("app.services.event_service.create_notification")
    @patch("app.services.event_service.generate_embedding", return_value=[...]) # (Leave return values as they are)
    @patch("app.services.event_service.supabase")

    def test_create_event_success(self, mock_sb, mock_embed, mock_notify): # <-- ADD mock_notify HERE
        event_row = {"id": "e1", "title": "Festival", "status": "active"}
        self._stub_chain(mock_sb, event_row)

        from app.services.event_service import create_event
        result = create_event("u1", {"title": "Festival", "description": "Fun", "category": "music"})

        assert result["id"] == "e1"
    @patch("app.services.event_service.create_notification") # ADD THIS
    @patch("app.services.event_service.generate_embedding", return_value=None)
    @patch("app.services.event_service.supabase")
    def test_create_event_sets_status_active(self, mock_sb, mock_embed, mock_notify):
        event_row = {"id": "e1", "status": "active"}
        self._stub_chain(mock_sb, event_row)

        from app.services.event_service import create_event
        create_event("u1", {"title": "X"})

        insert_payload = mock_sb.table.return_value.insert.call_args_list[0][0][0]
        assert insert_payload["status"] == "active"
    @patch("app.services.event_service.create_notification") # ADD THIS
    @patch("app.services.event_service.generate_embedding", return_value=None)
    @patch("app.services.event_service.supabase")
    def test_create_event_coerces_cost_to_int(self, mock_sb, mock_embed, mock_notify):
        event_row = {"id": "e1"}
        self._stub_chain(mock_sb, event_row)

        from app.services.event_service import create_event
        create_event("u1", {"title": "X", "cost": "9.99"})

        payload = mock_sb.table.return_value.insert.call_args_list[0][0][0]
        assert payload["cost"] == 9
        assert isinstance(payload["cost"], int)
    @patch("app.services.event_service.create_notification") # ADD THIS
    @patch("app.services.event_service.generate_embedding", return_value=None)
    @patch("app.services.event_service.supabase")
    def test_create_event_strips_id_field(self, mock_sb, mock_embed, mock_notify):
        event_row = {"id": "e1"}
        self._stub_chain(mock_sb, event_row)

        from app.services.event_service import create_event
        create_event("u1", {"title": "X", "id": "injected-id"})

        payload = mock_sb.table.return_value.insert.call_args_list[0][0][0]
        assert payload.get("id") is None or "injected-id" not in str(payload.get("id", ""))
    @patch("app.services.event_service.create_notification") # ADD THIS
    @patch("app.services.event_service.generate_embedding", return_value=None)
    @patch("app.services.event_service.supabase")
    def test_create_event_raises_400_on_empty_response(self, mock_sb, mock_embed, mock_notify):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.insert.return_value = chain
        chain.execute.return_value = MagicMock(data=[])

        from app.services.event_service import create_event
        with pytest.raises(HTTPException) as exc:
            create_event("u1", {"title": "X"})
        assert exc.value.status_code == 400
    @patch("app.services.event_service.create_notification") # ADD THIS
    @patch("app.services.event_service.generate_embedding", return_value=[0.1])
    @patch("app.services.event_service.supabase")
    def test_create_event_attaches_embedding(self, mock_sb, mock_embed, mock_notify):
        event_row = {"id": "e1"}
        self._stub_chain(mock_sb, event_row)

        from app.services.event_service import create_event
        create_event("u1", {"title": "X", "description": "Y", "category": "Z"})

        payload = mock_sb.table.return_value.insert.call_args_list[0][0][0]
        assert payload["event_embedding"] == [0.1]


# ──────────────────────────────────────────────
# update_event
# ──────────────────────────────────────────────

class TestUpdateEvent:
    def _existing_event(self, created_by="u1"):
        return {"id": "e1", "title": "Old", "description": "Desc", "category": "music",
                "created_by": created_by}

    @patch("app.services.event_service.create_notification")
    @patch("app.services.event_service.generate_embedding", return_value=None)
    @patch("app.services.event_service.supabase")
    def test_update_success(self, mock_sb, mock_embed, mock_notify):
        existing = self._existing_event()
        updated = {**existing, "title": "New"}

        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.update.return_value = chain
        chain.eq.return_value = chain
        chain.gte.return_value = chain
        chain.single.return_value = chain
        # Calls in order: get_event, update, participants, notifications
        chain.execute.side_effect = [
            MagicMock(data=existing),       # get_event
            MagicMock(data=[updated]),      # update
            MagicMock(data=[{"user_id": "u2"}]),  # participants
        ]

        from app.services.event_service import update_event
        result, _, _ = update_event("u1", "e1", {"title": "New"})

        assert result["title"] == "New"

    @patch("app.services.event_service.generate_embedding", return_value=None)
    @patch("app.services.event_service.supabase")
    def test_update_by_non_owner_raises_403(self, mock_sb, mock_embed):
        existing = self._existing_event(created_by="u1")
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.single.return_value = chain
        chain.execute.return_value = MagicMock(data=existing)

        from app.services.event_service import update_event
        with pytest.raises(HTTPException) as exc:
            update_event("other-user", "e1", {"title": "Hacked"})
        assert exc.value.status_code == 403

    @patch("app.services.event_service.create_notification")
    @patch("app.services.event_service.generate_embedding", return_value=[0.5])
    @patch("app.services.event_service.supabase")
    def test_update_regenerates_embedding_on_text_change(self, mock_sb, mock_embed, mock_notify):
        existing = self._existing_event()
        updated = {**existing, "title": "New"}
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.update.return_value = chain
        chain.eq.return_value = chain
        chain.gte.return_value = chain
        chain.single.return_value = chain
        chain.execute.side_effect = [
            MagicMock(data=existing),
            MagicMock(data=[updated]),
            MagicMock(data=[]),
        ]

        from app.services.event_service import update_event
        update_event("u1", "e1", {"title": "New"})

        mock_embed.assert_called_once()
        update_payload = chain.update.call_args_list[0][0][0]
        assert update_payload["event_embedding"] == [0.5]

    @patch("app.services.event_service.create_notification")
    @patch("app.services.event_service.generate_embedding", return_value=None)
    @patch("app.services.event_service.supabase")
    def test_update_coerces_max_capacity_to_int(self, mock_sb, mock_embed, mock_notify):
        existing = self._existing_event()
        updated = {**existing}
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.update.return_value = chain
        chain.eq.return_value = chain
        chain.gte.return_value = chain
        chain.single.return_value = chain
        chain.execute.side_effect = [
            MagicMock(data=existing),
            MagicMock(data=[updated]),
            MagicMock(data=[]),
        ]

        from app.services.event_service import update_event
        update_event("u1", "e1", {"max_capacity": "25.9"})

        payload = chain.update.call_args_list[0][0][0]
        assert payload["max_capacity"] == 25
        assert isinstance(payload["max_capacity"], int)


# ──────────────────────────────────────────────
# delete_event
# ──────────────────────────────────────────────

class TestDeleteEvent:
    @patch("app.services.event_service.get_username", return_value="john")
    @patch("app.services.event_service.supabase")
    def test_delete_success(self, mock_sb, mock_get_username):
        existing = {"id": "e1", "created_by": "u1"}
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.delete.return_value = chain
        chain.eq.return_value = chain
        chain.gte.return_value = chain
        chain.single.return_value = chain
        chain.execute.side_effect = [
            MagicMock(data=existing),
            MagicMock(data=[{"user_id": "u2"}]), # Add this mock response for the participants fetch
            MagicMock(data=[]),
        ]

        from app.services.event_service import delete_event
        result = delete_event("u1", "e1")

        assert result["message"] == "Event deleted successfully"

    @patch("app.services.event_service.supabase")
    def test_delete_by_non_owner_raises_403(self, mock_sb):
        existing = {"id": "e1", "created_by": "u1"}
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.single.return_value = chain
        chain.execute.return_value = MagicMock(data=existing)

        from app.services.event_service import delete_event
        with pytest.raises(HTTPException) as exc:
            delete_event("intruder", "e1")
        assert exc.value.status_code == 403


# ──────────────────────────────────────────────
# cancel_event
# ──────────────────────────────────────────────

class TestCancelEvent:
    @patch("app.services.event_service.get_username", return_value="john")
    @patch("app.services.event_service._email_participants")
    @patch("app.services.notification_service.create_notification")
    @patch("app.services.event_service.supabase")
    def test_cancel_success(self, mock_sb, mock_notify, mock_email, mock_get_username):
        mock_notify.return_value = None
        mock_email.return_value = None

        existing = {"id": "e1", "title": "Test Event", "created_by": "u1", "status": "active"}

        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.update.return_value = chain
        chain.delete.return_value = chain
        chain.eq.return_value = chain
        chain.single.return_value = chain

        chain.execute.side_effect = [
            MagicMock(data=existing),            # 1. get_event
            MagicMock(data=[]),                  # 2. update status
            MagicMock(data=[{"user_id": "u2"}]), # 3. select participants
            MagicMock(data=[]),                  # 4. delete participants
        ]

        from app.services.event_service import cancel_event
        result = cancel_event("u1", "e1")

        assert result["message"] == "Event cancelled"
        mock_notify.assert_called()
        mock_email.assert_called_once_with(existing, "cancellation")



# ──────────────────────────────────────────────
# get_all_events_by_user
# ──────────────────────────────────────────────

class TestGetAllEventsByUser:
    @patch("app.services.event_service.supabase")
    def test_returns_all_events(self, mock_sb):
        rows = [{"id": "e1"}, {"id": "e2"}]
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.order.return_value = chain
        chain.execute.return_value = MagicMock(data=rows)

        from app.services.event_service import get_all_events_by_user
        result = get_all_events_by_user("u1")

        assert result["total_count"] == 2
        assert result["data"] == rows
        assert result["status"] == "success"

    @patch("app.services.event_service.supabase")
    def test_raises_400_when_no_user_id(self, mock_sb):
        from app.services.event_service import get_all_events_by_user
        with pytest.raises(HTTPException) as exc:
            get_all_events_by_user("")
        assert exc.value.status_code == 400

    @patch("app.services.event_service.supabase")
    def test_returns_empty_list_gracefully(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.order.return_value = chain
        chain.execute.return_value = MagicMock(data=None)

        from app.services.event_service import get_all_events_by_user
        result = get_all_events_by_user("u1")

        assert result["data"] == []
        assert result["total_count"] == 0


# ──────────────────────────────────────────────
# list_events
# ──────────────────────────────────────────────

class TestListEvents:
    def _stub_standard_chain(self, mock_sb, rows):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.gte.return_value = chain
        chain.gt.return_value = chain
        chain.ilike.return_value = chain
        chain.order.return_value = chain
        chain.range.return_value = chain
        chain.execute.return_value = MagicMock(data=rows)
        return chain

    @patch("app.services.event_service.supabase")
    def test_standard_list_returns_data(self, mock_sb):
        rows = [{"id": "e1", "status": "active"}]
        self._stub_standard_chain(mock_sb, rows)

        from app.services.event_service import list_events
        result = list_events(page=1, limit=10)

        assert result["data"] == rows
        assert result["page"] == 1

    @patch("app.services.event_service.supabase")
    def test_category_filter_applied(self, mock_sb):
        self._stub_standard_chain(mock_sb, [])

        from app.services.event_service import list_events
        list_events(category="music")

        chain = mock_sb.table.return_value
        chain.eq.assert_any_call("category", "music")

    @patch("app.services.event_service.supabase")
    def test_city_filter_uses_ilike(self, mock_sb):
        self._stub_standard_chain(mock_sb, [])

        from app.services.event_service import list_events
        list_events(city="Berlin")

        chain = mock_sb.table.return_value
        chain.ilike.assert_called_once_with("location_name", "%Berlin%")

    @patch("app.services.event_service.generate_embedding", return_value=[0.1, 0.2])
    @patch("app.services.event_service.supabase")
    def test_search_uses_semantic_rpc(self, mock_sb, mock_embed):
        # 1. Setup mock dates: 'now' for the query, and 'future' for the data
        from datetime import datetime, timedelta
        future_date = (datetime.now() + timedelta(days=5)).isoformat()
        
        # 2. Mock data that satisfies: status='active' AND end_datetime > now
        rows = [
            {
                "id": "e1", 
                "title": "Future Fest", 
                "end_datetime": future_date, 
                "status": "active"
            }
        ]
        
        # 3. Setup the RPC chain
        rpc_mock = MagicMock()
        mock_sb.rpc.return_value = rpc_mock
        rpc_mock.execute.return_value = MagicMock(data=rows)

        from app.services.event_service import list_events
        result = list_events(search="outdoor festival")

        # 4. Assertions
        mock_sb.rpc.assert_called_once_with("search_events", {
            "query_embedding": [0.1, 0.2],
            "query_text": "outdoor festival",
            "match_count": 10,
        })
        
        # Verify the result contains our future event
        assert len(result["data"]) == 1
        assert result["data"][0]["id"] == "e1"
        # Verify the logic correctly identified it as active/upcoming
        assert result["data"][0]["status"] == "active"

    @patch("app.services.event_service.supabase")
    def test_pagination_range_correct(self, mock_sb):
        self._stub_standard_chain(mock_sb, [])

        from app.services.event_service import list_events
        list_events(page=3, limit=5)

        chain = mock_sb.table.return_value
        chain.range.assert_called_once_with(10, 14)

    @patch("app.services.event_service.supabase")

    def test_filters_out_expired_events(self, mock_sb):
        self._stub_standard_chain(mock_sb, [])

        from app.services.event_service import list_events
        list_events()

        chain = mock_sb.table.return_value
        # Verify gte was called on the date column (replace "event_date" with your actual column name)
        # This ensures the "upcoming only" logic is active
        from unittest.mock import ANY # Add this import at the top
        chain.gte.assert_any_call("end_datetime", ANY)


# ──────────────────────────────────────────────
# _update_event_side_effects
# ──────────────────────────────────────────────

class TestUpdateEventSideEffects:
    @patch("app.services.event_service._email_participants")
    @patch("app.services.event_service.create_notification")
    @patch("app.services.event_service.get_username", return_value="john")
    @patch("app.services.event_service.supabase")
    def test_notifies_updater_and_participants(self, mock_sb, mock_get_username, mock_create_notification, mock_email):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[{"user_id": "org1"}, {"user_id": "p1"}])

        from app.services.event_service import _update_event_side_effects
        _update_event_side_effects(
            "org1", "e1",
            {"title": "Tech Conference 2026"},
            {"id": "e1", "title": "Tech Conference 2026"},
        )

        mock_get_username.assert_called_once_with("org1")
        assert mock_create_notification.call_count == 2
        mock_create_notification.assert_any_call("org1", "e1", "event_updated", "Event 'Tech Conference 2026' was updated by john")
        mock_create_notification.assert_any_call("p1", "e1", "event_updated", "Event 'Tech Conference 2026' was updated by john")


def _stub_tables(mock_sb, chains):
    """Route mock_sb.table(name) to the chain registered for that table name."""
    mock_sb.table.side_effect = lambda name: chains[name]


# ──────────────────────────────────────────────
# delete_event notifications
# ──────────────────────────────────────────────

class TestDeleteEventNotifications:
    @patch("app.services.event_service._email_participants")
    @patch("app.services.event_service.create_notification")
    @patch("app.services.event_service.get_username", return_value="john")
    @patch("app.services.event_service.supabase")
    @patch("app.services.event_service.get_event")
    def test_notifies_participants_on_delete(self, mock_get_event, mock_sb, mock_get_username, mock_create_notification, mock_email):
        mock_get_event.return_value = {"id": "e1", "title": "Tech Conference 2026", "created_by": "org1"}

        participants_chain = MagicMock()
        participants_chain.select.return_value = participants_chain
        participants_chain.eq.return_value = participants_chain
        participants_chain.execute.return_value = MagicMock(data=[{"user_id": "p1"}])

        events_chain = MagicMock()
        events_chain.delete.return_value = events_chain
        events_chain.eq.return_value = events_chain
        events_chain.execute.return_value = MagicMock(data=[{"id": "e1"}])

        _stub_tables(mock_sb, {"event_participants": participants_chain, "events": events_chain})

        from app.services.event_service import delete_event
        delete_event("org1", "e1")

        mock_get_username.assert_called_once_with("org1")
        mock_create_notification.assert_called_once_with(
            "p1", "e1", "event_deleted", "Event 'Tech Conference 2026' was deleted by john"
        )


# ──────────────────────────────────────────────
# cancel_event notifications
# ──────────────────────────────────────────────

class TestCancelEventNotifications:
    @patch("app.services.event_service._email_participants")
    @patch("app.services.event_service.get_username", return_value="john")
    # cancel_event imports create_notification locally, so patch it at its source module
    @patch("app.services.notification_service.create_notification")
    @patch("app.services.event_service.supabase")
    @patch("app.services.event_service.get_event")
    def test_notifies_participants_on_cancel(self, mock_get_event, mock_sb, mock_create_notification, mock_get_username, mock_email):
        mock_get_event.return_value = {"id": "e1", "title": "Tech Conference 2026", "created_by": "org1"}

        events_chain = MagicMock()
        events_chain.update.return_value = events_chain
        events_chain.eq.return_value = events_chain

        participants_chain = MagicMock()
        participants_chain.select.return_value = participants_chain
        participants_chain.delete.return_value = participants_chain
        participants_chain.eq.return_value = participants_chain
        participants_chain.execute.return_value = MagicMock(data=[{"user_id": "p1"}])

        _stub_tables(mock_sb, {"events": events_chain, "event_participants": participants_chain})

        from app.services.event_service import cancel_event
        cancel_event("org1", "e1")

        mock_get_username.assert_called_once_with("org1")
        mock_create_notification.assert_called_once_with(
            "p1", "e1", "event_cancelled", "Event 'Tech Conference 2026' was cancelled by john"
        )

# ──────────────────────────────────────────────
# attach_organizers
# ──────────────────────────────────────────────

class TestAttachOrganizers:
    def _summary(self, uid, username):
        return {
            "id": uid,
            "username": username,
            "full_name": username.title(),
            "display_name": username,
            "avatar_kind": "icon",
            "icon_id": "icon_fox",
            "avatar_url": None,
        }

    @patch("app.services.event_service.get_user_summaries", create=True)
    @patch("app.services.event_service.supabase")
    def test_batches_and_dedupes_organizer_ids(self, mock_sb, mock_get_summaries):
        events = [
            {"id": "e1", "created_by": "u1"},
            {"id": "e2", "created_by": "u1"},
            {"id": "e3", "created_by": "u2"},
        ]
        mock_get_summaries.return_value = {
            "u1": self._summary("u1", "jill5"),
            "u2": self._summary("u2", "tom9"),
        }

        from app.services.event_service import attach_organizers
        attach_organizers(events)

        mock_get_summaries.assert_called_once()
        called_ids = mock_get_summaries.call_args.args[0]
        assert sorted(set(called_ids)) == ["u1", "u2"]
        assert len(list(called_ids)) == 2
        mock_sb.table.assert_not_called()

        assert events[0]["organizer"] == self._summary("u1", "jill5")
        assert events[1]["organizer"] == self._summary("u1", "jill5")
        assert events[2]["organizer"] == self._summary("u2", "tom9")
        assert events[0]["organizer"] is not events[1]["organizer"]

        # Mutating one event's organizer must not affect the other event
        # or the mock's underlying summary dict.
        events[0]["organizer"]["username"] = "changed"
        assert events[1]["organizer"]["username"] == "jill5"
        assert mock_get_summaries.return_value["u1"]["username"] == "jill5"

    @patch("app.services.event_service.get_user_summaries", create=True)
    def test_mutates_in_place_and_returns_same_list(self, mock_get_summaries):
        mock_get_summaries.return_value = {"u1": self._summary("u1", "jill5")}
        events = [{"id": "e1", "created_by": "u1", "title": "Party"}]

        from app.services.event_service import attach_organizers
        result = attach_organizers(events)

        assert result is events
        assert events[0]["organizer"] == self._summary("u1", "jill5")
        assert events[0]["title"] == "Party"
        assert events[0]["id"] == "e1"

    @patch("app.services.event_service.get_user_summaries", create=True)
    def test_skips_none_and_non_dict_items(self, mock_get_summaries):
        mock_get_summaries.return_value = {"u1": self._summary("u1", "jill5")}
        events = [{"id": "e1", "created_by": "u1"}, None, "not-a-dict", 42]

        from app.services.event_service import attach_organizers
        result = attach_organizers(events)

        assert result[1] is None
        assert result[2] == "not-a-dict"
        assert result[3] == 42
        assert result[0]["organizer"] == self._summary("u1", "jill5")

    @patch("app.services.event_service.get_user_summaries", create=True)
    @patch("app.services.event_service.supabase")
    def test_empty_input_no_summaries_call_no_supabase_query(self, mock_sb, mock_get_summaries):
        from app.services.event_service import attach_organizers
        result = attach_organizers([])

        assert result == []
        mock_get_summaries.assert_not_called()
        mock_sb.table.assert_not_called()

    @patch("app.services.event_service.get_user_summaries", create=True)
    @patch("app.services.event_service.supabase")
    def test_only_none_items_no_summaries_call(self, mock_sb, mock_get_summaries):
        from app.services.event_service import attach_organizers
        events = [None, None]
        attach_organizers(events)

        mock_get_summaries.assert_not_called()
        mock_sb.table.assert_not_called()

    @patch("app.services.event_service.get_user_summaries", create=True)
    @patch("app.services.event_service.supabase")
    def test_only_created_by_none_no_summaries_call(self, mock_sb, mock_get_summaries):
        from app.services.event_service import attach_organizers
        events = [{"id": "e1", "created_by": None}]
        attach_organizers(events)

        mock_get_summaries.assert_not_called()
        mock_sb.table.assert_not_called()
        assert events[0]["organizer"] is None

    @patch("app.services.event_service.get_user_summaries", create=True)
    def test_missing_summary_gets_stub(self, mock_get_summaries):
        from app.services.profile_service import build_user_summary
        mock_get_summaries.return_value = {}
        events = [{"id": "e1", "created_by": "u1"}]

        from app.services.event_service import attach_organizers
        attach_organizers(events)

        assert events[0]["organizer"] == build_user_summary(None, "u1")

    @patch("app.services.event_service.get_user_summaries", create=True)
    def test_d6_backfill_looks_up_missing_created_by(self, mock_get_summaries):
        from tests._supabase_mock import make_table_router
        mock_sb, chains = make_table_router()
        chains["events"].execute.return_value = MagicMock(
            data=[{"id": "e1", "created_by": "u1"}]
        )
        mock_get_summaries.return_value = {"u1": self._summary("u1", "jill5")}

        with patch("app.services.event_service.supabase", mock_sb):
            from app.services.event_service import attach_organizers
            events = [{"id": "e1", "title": "No creator key"}]
            attach_organizers(events)

        chains["events"].select.assert_any_call("id, created_by")
        chains["events"].in_.assert_any_call("id", ["e1"])
        assert "created_by" not in events[0]
        assert events[0]["organizer"] == self._summary("u1", "jill5")

        event_query_count = [c.args[0] for c in mock_sb.table.call_args_list].count("events")
        assert event_query_count == 1

    @patch("app.services.event_service.get_user_summaries", create=True)
    def test_no_events_query_when_all_rows_have_created_by_key(self, mock_get_summaries):
        from tests._supabase_mock import make_table_router
        mock_sb, chains = make_table_router()
        mock_get_summaries.return_value = {"u1": self._summary("u1", "jill5")}

        with patch("app.services.event_service.supabase", mock_sb):
            from app.services.event_service import attach_organizers
            events = [{"id": "e1", "created_by": None}, {"id": "e2", "created_by": "u1"}]
            attach_organizers(events)

        event_query_count = [c.args[0] for c in mock_sb.table.call_args_list].count("events")
        assert event_query_count == 0

    @patch("app.services.event_service.get_user_summaries", create=True)
    def test_d6_backfill_no_row_found_gives_none_organizer(self, mock_get_summaries):
        from tests._supabase_mock import make_table_router
        mock_sb, chains = make_table_router()
        chains["events"].execute.return_value = MagicMock(data=[])
        mock_get_summaries.return_value = {}

        with patch("app.services.event_service.supabase", mock_sb):
            from app.services.event_service import attach_organizers
            events = [{"id": "e1", "title": "No creator key"}]
            attach_organizers(events)

        assert events[0]["organizer"] is None
        mock_get_summaries.assert_not_called()

    @patch("app.services.event_service.get_user_summaries", create=True)
    def test_d6_backfill_query_raises_no_exception_and_others_still_get_summaries(self, mock_get_summaries, caplog):
        from tests._supabase_mock import make_table_router
        mock_sb, chains = make_table_router()
        chains["events"].execute.side_effect = Exception("db down")
        mock_get_summaries.return_value = {"u2": self._summary("u2", "tom9")}

        with patch("app.services.event_service.supabase", mock_sb):
            from app.services.event_service import attach_organizers
            events = [
                {"id": "e1", "title": "No creator key"},
                {"id": "e2", "created_by": "u2"},
            ]
            with caplog.at_level(logging.ERROR, logger="app.services.event_service"):
                result = attach_organizers(events)

        assert result[0]["organizer"] is None
        assert result[1]["organizer"] == self._summary("u2", "tom9")
        error_records = [record for record in caplog.records if record.levelname == "ERROR"]
        assert len(error_records) == 1
        assert error_records[0].exc_info is not None

    @patch("app.services.event_service.get_user_summaries", create=True)
    def test_get_user_summaries_raising_gives_stubs_not_exception(self, mock_get_summaries, caplog):
        from app.services.profile_service import build_user_summary
        mock_get_summaries.side_effect = Exception("summary service down")
        events = [{"id": "e1", "created_by": "u1"}]

        from app.services.event_service import attach_organizers
        with caplog.at_level(logging.ERROR, logger="app.services.event_service"):
            result = attach_organizers(events)

        assert result[0]["organizer"] == build_user_summary(None, "u1")
        error_records = [record for record in caplog.records if record.levelname == "ERROR"]
        assert len(error_records) == 1
        assert error_records[0].exc_info is not None

    @patch("app.services.event_service.get_user_summaries", create=True)
    def test_d6_backfill_warns_when_some_ids_not_found(self, mock_get_summaries, caplog):
        from tests._supabase_mock import make_table_router
        mock_sb, chains = make_table_router()
        chains["events"].execute.return_value = MagicMock(
            data=[{"id": "e1", "created_by": "u1"}]
        )
        mock_get_summaries.return_value = {"u1": self._summary("u1", "jill5")}

        with patch("app.services.event_service.supabase", mock_sb):
            from app.services.event_service import attach_organizers
            events = [
                {"id": "e1", "title": "No creator key"},
                {"id": "e2", "title": "No creator key either"},
            ]
            with caplog.at_level(logging.WARNING, logger="app.services.event_service"):
                attach_organizers(events)

        warning_records = [record for record in caplog.records if record.levelname == "WARNING"]
        assert len(warning_records) == 1
        assert "e2" in warning_records[0].getMessage()

    @patch("app.services.event_service.get_user_summaries", create=True)
    def test_d6_backfill_no_warning_when_all_ids_found(self, mock_get_summaries, caplog):
        from tests._supabase_mock import make_table_router
        mock_sb, chains = make_table_router()
        chains["events"].execute.return_value = MagicMock(
            data=[{"id": "e1", "created_by": "u1"}]
        )
        mock_get_summaries.return_value = {"u1": self._summary("u1", "jill5")}

        with patch("app.services.event_service.supabase", mock_sb):
            from app.services.event_service import attach_organizers
            events = [{"id": "e1", "title": "No creator key"}]
            with caplog.at_level(logging.WARNING, logger="app.services.event_service"):
                attach_organizers(events)

        warning_records = [record for record in caplog.records if record.levelname == "WARNING"]
        assert len(warning_records) == 0


# ──────────────────────────────────────────────
# unchanged by attach_organizers
# ──────────────────────────────────────────────

class TestEventServiceUnchangedByOrganizers:
    @patch("app.services.event_service.get_user_summaries", create=True)
    @patch("app.services.event_service.supabase")
    def test_get_event_has_no_organizer_key(self, mock_sb, mock_get_summaries):
        event = {"id": "e1", "title": "Party"}
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.single.return_value = chain
        chain.execute.return_value = MagicMock(data=event)

        from app.services.event_service import get_event
        result = get_event("e1")

        assert result == event
        assert "organizer" not in result
        mock_get_summaries.assert_not_called()

    @patch("app.services.event_service.get_user_summaries", create=True)
    @patch("app.services.event_service.supabase")
    def test_list_events_standard_filter_has_no_organizer_key(self, mock_sb, mock_get_summaries):
        rows = [{"id": "e1", "status": "active"}]
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.gte.return_value = chain
        chain.gt.return_value = chain
        chain.ilike.return_value = chain
        chain.order.return_value = chain
        chain.range.return_value = chain
        chain.execute.return_value = MagicMock(data=rows)

        from app.services.event_service import list_events
        result = list_events(page=1, limit=10)

        assert result["data"] == rows
        assert all("organizer" not in item for item in result["data"])
        mock_get_summaries.assert_not_called()

    @patch("app.services.event_service.get_user_summaries", create=True)
    @patch("app.services.event_service.generate_embedding", return_value=[0.1, 0.2])
    @patch("app.services.event_service.supabase")
    def test_list_events_semantic_search_has_no_organizer_key(self, mock_sb, mock_embed, mock_get_summaries):
        from datetime import datetime, timedelta
        future_date = (datetime.now() + timedelta(days=5)).isoformat()

        rows = [
            {
                "id": "e1",
                "title": "Future Fest",
                "end_datetime": future_date,
                "status": "active",
            }
        ]

        rpc_mock = MagicMock()
        mock_sb.rpc.return_value = rpc_mock
        rpc_mock.execute.return_value = MagicMock(data=rows)

        from app.services.event_service import list_events
        result = list_events(search="outdoor festival")

        assert len(result["data"]) == 1
        assert "organizer" not in result["data"][0]
        mock_get_summaries.assert_not_called()

    @patch("app.services.event_service.get_user_summaries", create=True)
    @patch("app.services.event_service.supabase")
    def test_get_all_events_by_user_has_no_organizer_key(self, mock_sb, mock_get_summaries):
        rows = [{"id": "e1"}, {"id": "e2"}]
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.order.return_value = chain
        chain.execute.return_value = MagicMock(data=rows)

        from app.services.event_service import get_all_events_by_user
        result = get_all_events_by_user("u1")

        assert result["data"] == rows
        assert all("organizer" not in item for item in result["data"])
        mock_get_summaries.assert_not_called()
