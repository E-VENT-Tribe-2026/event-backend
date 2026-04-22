import pytest
from unittest.mock import patch, MagicMock
from app.utils.embedding_helper import generate_embedding

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
    def test_generate_embedding_failure_returns_none(self, mock_mxbai_class, capsys):
        mock_client = MagicMock()
        mock_client.embed.side_effect = Exception("API Timeout")
        mock_mxbai_class.return_value = mock_client

        result = generate_embedding("fail text")

        assert result is None
        captured = capsys.readouterr()
        assert "Embedding generation failed: API Timeout" in captured.out