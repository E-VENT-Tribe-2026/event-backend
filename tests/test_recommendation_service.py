import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException
from app.services.recommendation_service import (
    _parse_embedding,
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