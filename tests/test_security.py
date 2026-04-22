import pytest
from fastapi import HTTPException
from unittest.mock import patch
from app.core.security import verify_token

class TestSecurity:
    @patch("app.core.security.settings")
    @patch("app.core.security.jwt.decode")
    def test_verify_token_success(self, mock_decode, mock_settings):
        mock_settings.SUPABASE_JWT_SECRET = "supersecret"
        mock_decode.return_value = {"sub": "123", "role": "authenticated"}

        payload = verify_token("valid.jwt.token")

        assert payload["sub"] == "123"
        mock_decode.assert_called_once_with(
            "valid.jwt.token",
            "supersecret",
            algorithms=["HS256"],
            options={"verify_aud": False}
        )

    @patch("app.core.security.jwt.decode")
    def test_verify_token_invalid_raises_401(self, mock_decode):
        from jose import JWTError
        mock_decode.side_effect = JWTError("Expired signature")

        with pytest.raises(HTTPException) as exc:
            verify_token("expired.jwt.token")
            
        assert exc.value.status_code == 401
        assert "Invalid or expired token" in exc.value.detail