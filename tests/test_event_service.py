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
        chain.gte.return_value = chain  # <--- ADD THIS
        chain.single.return_value = chain
        chain.execute.return_value = MagicMock(data=event)

        from app.services.event_service import get_event
        assert get_event("e1") == event
        # Optional: verify gte was called with a date string
        chain.gte.assert_called_once()

    @patch("app.services.event_service.supabase")
    def test_raises_404_when_missing(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.gte.return_value = chain  # <--- ADD THIS
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
        result = update_event("u1", "e1", {"title": "New"})

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
    @patch("app.services.event_service.supabase")
    def test_delete_success(self, mock_sb):
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
    # 1. Patch the SOURCE module so the local import inside cancel_event gets the mock
    @patch("app.services.notification_service.create_notification")
    @patch("app.services.event_service.supabase") 
    def test_cancel_success(self, mock_sb, mock_notify):
        # NOTE: If VS Code shows red squiggles, swap names to (self, mock_notify, mock_sb)
        
        # 2. Block the real logic before it hits Postgres
        mock_notify.return_value = None 
        
        existing = {"id": "e1", "title": "Test Event", "created_by": "u1", "status": "active"}
        
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.update.return_value = chain
        chain.delete.return_value = chain
        chain.eq.return_value = chain
        chain.gte.return_value = chain
        chain.single.return_value = chain
        
        # 3. Side effects for the 4 DB calls in cancel_event
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