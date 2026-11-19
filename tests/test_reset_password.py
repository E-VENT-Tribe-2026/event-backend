"""Tests for POST /api/auth/reset-password token verification (ticket #273).

The reset token must be verified (signature, expiry, audience, issuer) before the
password is changed for its `sub`.
"""
import base64
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from jose import jwt
from jose.exceptions import JWKError

from app.core import jwt_middleware
from app.core.jwt_middleware import JWKSUnavailableError
from app.core.limiter import limiter
from app.main import app
from app.services import auth_service

SUPABASE_URL = "https://test.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"
HS_SECRET = "test-legacy-secret"
NEW_PASSWORD = "brand-new-password-1"
INVALID_DETAIL = "Invalid or expired reset token."
OUTAGE_DETAIL = "Could not verify the reset link right now. Please try again."

client = TestClient(app)


def _claims(**overrides):
    claims = {
        "sub": "u1",
        "aud": "authenticated",
        "iss": ISSUER,
        "exp": int(time.time()) + 3600,
    }
    claims.update(overrides)
    return claims


def _hs256(secret=HS_SECRET, drop=(), **claims):
    body = _claims(**claims)
    for key in drop:
        body.pop(key, None)
    return jwt.encode(body, secret, algorithm="HS256")


def _es256_token():
    private = ec.generate_private_key(ec.SECP256R1())
    pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return jwt.encode(_claims(), pem, algorithm="ES256", headers={"kid": "test-kid"})


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    # conftest sets TESTING=true, which makes JWTMiddleware skip; enforce it here.
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.setattr(
        jwt_middleware, "settings",
        SimpleNamespace(SUPABASE_URL=SUPABASE_URL, SUPABASE_JWT_SECRET=HS_SECRET),
    )
    monkeypatch.setattr(jwt_middleware, "_jwks_cache", {"keys": {}, "fetched_at": 0.0})
    monkeypatch.setattr(jwt_middleware, "_fetch_jwks", AsyncMock(return_value={}))
    # The route is limited to 5/minute per IP; start every test with a clean slate.
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def admin():
    """Patch supabase.create_client; yields (create_client mock, update_user_by_id mock)."""
    with patch("supabase.create_client") as create_client:
        yield create_client, create_client.return_value.auth.admin.update_user_by_id


def _assert_never_applied(admin):
    create_client, update = admin
    create_client.assert_not_called()
    update.assert_not_called()


def _bad_tokens():
    header, payload, _ = _hs256().split(".")
    return {
        "forged_signature": f"{header}.{payload}.not-a-real-signature",
        "wrong_secret": _hs256(secret="guessed"),
        "expired": _hs256(exp=int(time.time()) - 10),
        "wrong_audience": _hs256(aud="anon"),
        "wrong_issuer": _hs256(iss="https://evil.example.com/auth/v1"),
        "alg_none": f"{_b64url(json.dumps({'alg': 'none', 'typ': 'JWT'}).encode())}.{payload}.",
        "not_a_jwt": "garbage",
        "two_segments": "abc.def",
        "four_segments": "a.b.c.d",
        "no_sub": _hs256(drop=("sub",)),
        "empty_sub": _hs256(sub=""),
        "non_string_sub": _hs256(sub=123),
        "whitespace_sub": _hs256(sub="   "),
    }


BAD_TOKEN_IDS = list(_bad_tokens())


class TestResetPasswordService:
    @pytest.mark.parametrize("case", BAD_TOKEN_IDS)
    def test_rejected_token_gives_401_and_never_updates(self, admin, case):
        token = _bad_tokens()[case]
        with pytest.raises(HTTPException) as exc:
            auth_service.reset_password(token, NEW_PASSWORD)
        assert exc.value.status_code == 401
        assert exc.value.detail == INVALID_DETAIL
        _assert_never_applied(admin)

    def test_valid_token_updates_password(self, admin):
        _, update = admin
        result = auth_service.reset_password(_hs256(sub="u1"), NEW_PASSWORD)
        assert result == {"message": "Password updated successfully."}
        update.assert_called_once_with("u1", {"password": NEW_PASSWORD})

    def test_user_id_comes_from_verified_sub(self, admin):
        _, update = admin
        auth_service.reset_password(_hs256(sub="real-user"), NEW_PASSWORD)
        update.assert_called_once_with("real-user", {"password": NEW_PASSWORD})

    def test_key_outage_gives_503_and_never_updates(self, admin):
        with patch(
            "app.services.auth_service.verify_jwt",
            AsyncMock(side_effect=JWKSUnavailableError("down")),
        ):
            with pytest.raises(HTTPException) as exc:
                auth_service.reset_password(_hs256(), NEW_PASSWORD)
        assert exc.value.status_code == 503
        assert exc.value.detail == OUTAGE_DETAIL
        _assert_never_applied(admin)

    @pytest.mark.parametrize("exc", [JWKError("x"), KeyError("x")])
    def test_unexpected_verifier_error_fails_closed_503(self, admin, exc):
        with patch("app.services.auth_service.verify_jwt", AsyncMock(side_effect=exc)):
            with pytest.raises(HTTPException) as e:
                auth_service.reset_password(_hs256(), NEW_PASSWORD)
        assert e.value.status_code == 503
        assert e.value.detail == OUTAGE_DETAIL
        _assert_never_applied(admin)

    def test_real_jwks_outage_gives_503(self, admin, monkeypatch):
        monkeypatch.setattr(
            jwt_middleware, "_fetch_jwks", AsyncMock(side_effect=Exception("down"))
        )
        with pytest.raises(HTTPException) as e:
            auth_service.reset_password(_es256_token(), NEW_PASSWORD)
        assert e.value.status_code == 503
        assert e.value.detail == OUTAGE_DETAIL
        _assert_never_applied(admin)


def _post(token, **extra):
    return client.post(
        "/api/auth/reset-password",
        json={"access_token": token, "new_password": NEW_PASSWORD, **extra},
    )


class TestResetPasswordRoute:
    def test_valid_token_without_authorization_header(self, admin):
        _, update = admin
        response = _post(_hs256(sub="route-user"))
        assert response.status_code == 200
        assert response.json() == {"message": "Password updated successfully."}
        update.assert_called_once_with("route-user", {"password": NEW_PASSWORD})

    def test_forged_token_gives_401(self, admin):
        header, payload, _ = _hs256().split(".")
        response = _post(f"{header}.{payload}.not-a-real-signature")
        assert response.status_code == 401
        assert response.json()["detail"] == INVALID_DETAIL
        _assert_never_applied(admin)

    def test_key_outage_gives_503(self, admin):
        with patch(
            "app.services.auth_service.verify_jwt",
            AsyncMock(side_effect=JWKSUnavailableError("down")),
        ):
            response = _post(_hs256())
        assert response.status_code == 503
        assert response.json()["detail"] == OUTAGE_DETAIL
        _assert_never_applied(admin)

    def test_current_password_field_is_ignored(self, admin):
        _, update = admin
        response = _post(_hs256(sub="u1"), current_password="definitely-wrong")
        assert response.status_code == 200
        update.assert_called_once_with("u1", {"password": NEW_PASSWORD})
