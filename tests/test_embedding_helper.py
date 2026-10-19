import pytest
from unittest.mock import patch, MagicMock
from app.utils.embedding_helper import cosine_similarity, generate_embedding, parse_embedding

class TestEmbeddingHelper:
    @patch("app.utils.embedding_helper.os.environ.get", return_value="fake_key")
    @patch("app.utils.embedding_helper.Mixedbread")
    def test_generate_embedding_success(self, mock_mxbai_class, mock_env):
        mock_client = MagicMock()
        mock_mxbai_class.return_value = mock_client
        
        # Mock the deep response object
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.5, 0.5])]
        mock_client.embed.return_value = mock_response

        result = generate_embedding("hello world")

        assert result == [0.5, 0.5]
        mock_client.embed.assert_called_once_with(
            model="mixedbread-ai/mxbai-embed-large-v1",
            input=["hello world"],
            normalized=True,
            encoding_format="float"
        )

    @patch("app.utils.embedding_helper.Mixedbread")
    def test_generate_embedding_failure_returns_none(self, mock_mxbai_class):
        mock_client = MagicMock()
        mock_client.embed.side_effect = Exception("API Timeout")
        mock_mxbai_class.return_value = mock_client

        with patch("app.utils.embedding_helper.logger") as mock_logger:
            result = generate_embedding("fail text")
            assert result is None
            mock_logger.error.assert_called_once()
            assert "API Timeout" in str(mock_logger.error.call_args)


class TestParseEmbedding:
    def test_none_and_empty(self):
        assert parse_embedding(None) is None
        assert parse_embedding("") is None
        assert parse_embedding("   ") is None
        assert parse_embedding([]) is None

    def test_list_and_json_string(self):
        assert parse_embedding([1, 2.5]) == [1.0, 2.5]
        assert parse_embedding("[0.1, 0.2]") == [0.1, 0.2]

    def test_invalid(self):
        assert parse_embedding("not-json") is None
        assert parse_embedding(["x"]) is None


class TestCosineSimilarity:
    def test_identical_orthogonal_opposite(self):
        assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
        assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

    def test_incomparable(self):
        assert cosine_similarity([], [1.0]) is None
        assert cosine_similarity([1.0], [1.0, 0.0]) is None
        assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) is None