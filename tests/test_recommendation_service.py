import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException
from app.services.recommendation_service import (
    _parse_embedding,
    _parse_interests,
    _average_embeddings,
    _blend_embeddings,
    get_recommendations
)

class TestRecommendationHelpers:
    def test_parse_embedding(self):
        # String JSON representation from Supabase
        assert _parse_embedding("[0.1, 0.2]") == [0.1, 0.2]
        # Direct list
        assert _parse_embedding([0.1, 0.2]) == [0.1, 0.2]
        # None
        assert _parse_embedding(None) is None
        # Empty string / empty list
        assert _parse_embedding("") is None
        assert _parse_embedding("[]") is None
        assert _parse_embedding([]) is None
        # Invalid string
        assert _parse_embedding("invalid") is None

    def test_parse_interests(self):
        # List of strings
        assert _parse_interests(["music", "sports"]) == ["music", "sports"]
        # Postgres array string
        assert _parse_interests("{music,sports}") == ["music", "sports"]
        # Postgres array with quotes and spaces
        assert _parse_interests('{"music", "sports"}') == ["music", "sports"]
        # JSON array string
        assert _parse_interests('["music", "sports"]') == ["music", "sports"]
        # Comma-separated string
        assert _parse_interests("music, sports") == ["music", "sports"]
        # Single string
        assert _parse_interests("music") == ["music"]
        # Empty / None
        assert _parse_interests(None) == []
        assert _parse_interests("") == []
        assert _parse_interests([]) == []

    def test_average_embeddings(self):
        embs = [[1.0, 2.0], [3.0, 4.0]]
        assert _average_embeddings(embs) == [2.0, 3.0]
        assert _average_embeddings([]) is None

    def test_blend_embeddings(self):
        sources = [
            ([1.0, 1.0], 0.5),
            ([0.0, 0.0], 0.5)
        ]
        assert _blend_embeddings(sources) == [0.5, 0.5]
        
        # Ignores None embeddings
        sources_with_none = [
            (None, 0.5),
            ([2.0, 2.0], 0.5)
        ]
        assert _blend_embeddings(sources_with_none) == [2.0, 2.0]

class TestGetRecommendations:
    @patch("app.services.recommendation_service.supabase")
    @patch("app.services.recommendation_service.generate_embedding")
    def test_get_recommendations_success(self, mock_embed, mock_sb):
        # 1. Mock _fetch_profile
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.single.return_value = chain
        
        # Side effects for the 4 table queries: profile, joined, saved, seen
        chain.execute.side_effect = [
            MagicMock(data={"interests": ["music"], "bio": "DJ", "interest_embedding": None}), # Profile
            MagicMock(data=[{"events": {"event_embedding": "[0.2]"}}]), # Joined
            MagicMock(data=[{"events": {"event_embedding": "[0.3]"}}]), # Saved
            MagicMock(data=[{"event_id": "e_old"}]), # Seen joined
            MagicMock(data=[]) # Seen saved
        ]
        
        mock_embed.return_value = [0.1] # For the on-the-fly interest embedding
        
        # Mock the RPC call for semantic search
        mock_sb.rpc.return_value.execute.return_value = MagicMock(data=[
            {"id": "e_new", "end_datetime": "2099-01-01T00:00:00", "status": "active"},
            {"id": "e_old", "end_datetime": "2099-01-01T00:00:00", "status": "active"} # Should be filtered out
        ])

        result = get_recommendations("u1", limit=10)

        assert result["user_id"] == "u1"
        assert result["total"] == 1
        assert result["data"][0]["id"] == "e_new" # Filters out e_old

    @patch("app.services.recommendation_service.supabase")
    def test_get_recommendations_no_profile_data_raises_400(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.single.return_value = chain
        
        # Return a profile with absolutely no data and no history
        chain.execute.side_effect = [
            MagicMock(data={"interests": [], "bio": "", "interest_embedding": None}),
            MagicMock(data=[]),
            MagicMock(data=[]),
        ]

        with pytest.raises(HTTPException) as exc:
            get_recommendations("empty_user")
        assert exc.value.status_code == 400

    @patch("app.services.recommendation_service.supabase")
    @patch("app.services.recommendation_service.generate_embedding")
    def test_get_recommendations_with_postgres_array_interests(self, mock_embed, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.single.return_value = chain

        # Profile with postgres array string interests
        chain.execute.side_effect = [
            MagicMock(data={"interests": "{sports,music}", "bio": "", "interest_embedding": None}),
            MagicMock(data=[]), # Joined
            MagicMock(data=[]), # Saved
            MagicMock(data=[]), # Seen joined
            MagicMock(data=[]), # Seen saved
        ]
        mock_embed.return_value = [0.1, 0.2]
        mock_sb.rpc.return_value.execute.return_value = MagicMock(data=[
            {"id": "e_sports", "end_datetime": "2099-01-01T00:00:00", "status": "active"},
        ])

        result = get_recommendations("u2", limit=10)

        # Verify generate_embedding was called with words joined by space, NOT space-separated characters
        mock_embed.assert_called_once_with("sports music")
        assert result["total"] == 1
        assert result["data"][0]["id"] == "e_sports"

    @patch("app.services.recommendation_service.supabase")
    @patch("app.services.recommendation_service.generate_embedding")
    def test_get_recommendations_candidate_count_and_filtering(self, mock_embed, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.single.return_value = chain

        chain.execute.side_effect = [
            MagicMock(data={"interests": ["sports"], "bio": "", "interest_embedding": None}),
            MagicMock(data=[]), # Joined
            MagicMock(data=[]), # Saved
            MagicMock(data=[{"event_id": "e_joined"}]), # Seen joined
            MagicMock(data=[]), # Seen saved
        ]
        mock_embed.return_value = [0.5, 0.5]

        # Simulate search_events returning past, inactive, and joined events along with upcoming events
        mock_sb.rpc.return_value.execute.return_value = MagicMock(data=[
            {"id": "e_past", "end_datetime": "2020-01-01T00:00:00", "status": "active"},
            {"id": "e_inactive", "end_datetime": "2099-01-01T00:00:00", "status": "cancelled"},
            {"id": "e_joined", "end_datetime": "2099-01-01T00:00:00", "status": "active"},
            {"id": "e_upcoming", "end_datetime": "2099-01-01T00:00:00", "status": "active"},
        ])

        result = get_recommendations("u3", limit=10)

        # Verify candidate pool was at least 100
        rpc_call_args = mock_sb.rpc.call_args[0]
        assert rpc_call_args[0] == "search_events"
        assert rpc_call_args[1]["match_count"] >= 100

        # Verify past, inactive, and already seen events were filtered out
        assert result["total"] == 1
        assert result["data"][0]["id"] == "e_upcoming"