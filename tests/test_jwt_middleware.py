import asyncio
import base64
import hashlib
import hmac
import json
import time
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from jose import jwk, jwt

from app.core import jwt_middleware
from app.core.jwt_middleware import InvalidTokenError, JWKSUnavailableError, verify_jwt
from app.main import app

SUPABASE_URL = "https://test.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"
HS_SECRET = "test-legacy-secret"
KID = "test-kid"


def _ec_keypair():
    private = ec.generate_private_key(ec.SECP256R1())
    private_pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    public_jwk = jwk.construct(public_pem, "ES256").to_dict()
    return private_pem, {**public_jwk, "kid": KID, "alg": "ES256", "use": "sig"}


PRIVATE_PEM, PUBLIC_JWK = _ec_keypair()
ATTACKER_PEM, _ = _ec_keypair()


def _claims(**overrides):
    claims = {
        "sub": "u1",
        "aud": "authenticated",
        "iss": ISSUER,
        "exp": int(time.time()) + 3600,
    }
    claims.update(overrides)
    return claims


def _es256(key=PRIVATE_PEM, kid=KID, **claims):
    return jwt.encode(_claims(**claims), key, algorithm="ES256", headers={"kid": kid})


def _hs256(secret=HS_SECRET, **claims):
    return jwt.encode(_claims(**claims), secret, algorithm="HS256")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setattr(
        jwt_middleware, "settings",
        SimpleNamespace(SUPABASE_URL=SUPABASE_URL, SUPABASE_JWT_SECRET=HS_SECRET),
    )
    monkeypatch.setattr(jwt_middleware, "_jwks_cache", {"keys": {}, "fetched_at": 0.0})
    fetch = AsyncMock(return_value={KID: PUBLIC_JWK})
    monkeypatch.setattr(jwt_middleware, "_fetch_jwks", fetch)
    return fetch


def _verify(token):
    return asyncio.run(verify_jwt(token))


class TestVerifyJwt:
    def test_valid_es256_token_is_accepted(self):
        assert _verify(_es256())["sub"] == "u1"

    def test_valid_hs256_token_is_accepted(self):
        assert _verify(_hs256())["sub"] == "u1"

    def test_es256_token_signed_by_other_key_is_rejected(self):
        with pytest.raises(InvalidTokenError):
            _verify(_es256(key=ATTACKER_PEM))

    def test_hs256_token_with_wrong_secret_is_rejected(self):
        with pytest.raises(InvalidTokenError):
            _verify(_hs256(secret="guessed"))

    def test_forged_signature_is_rejected(self):
        header, payload, _ = _es256().split(".")
        with pytest.raises(InvalidTokenError):
            _verify(f"{header}.{payload}.not-a-real-signature")

    def test_alg_none_is_rejected(self):
        header, payload, _ = jwt.encode(_claims(), HS_SECRET, algorithm="HS256").split(".")
        none_header = "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0"  # {"alg":"none","typ":"JWT"}
        with pytest.raises(InvalidTokenError):
            _verify(f"{none_header}.{payload}.")

    def test_expired_token_is_rejected(self):
        with pytest.raises(InvalidTokenError):
            _verify(_es256(exp=int(time.time()) - 10))

    def test_wrong_audience_is_rejected(self):
        with pytest.raises(InvalidTokenError):
            _verify(_es256(aud="anon"))

    def test_wrong_issuer_is_rejected(self):
        with pytest.raises(InvalidTokenError):
            _verify(_es256(iss="https://evil.example.com/auth/v1"))

    def test_malformed_token_is_rejected(self):
        with pytest.raises(InvalidTokenError):
            _verify("not.a.jwt")

    def test_hs256_header_on_es256_key_material_is_rejected(self):
        # Algorithm confusion: HS256 is only ever checked against the shared secret.
        # jose refuses to sign with a PEM as HMAC secret, so forge it by hand.
        public_pem = jwk.construct(PUBLIC_JWK).to_pem()
        header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT", "kid": KID}).encode())
        payload = _b64url(json.dumps(_claims()).encode())
        signature = _b64url(hmac.new(public_pem, f"{header}.{payload}".encode(), hashlib.sha256).digest())
        with pytest.raises(InvalidTokenError):
            _verify(f"{header}.{payload}.{signature}")


class TestJwksCache:
    def test_keys_are_cached_between_requests(self, _isolated):
        _verify(_es256())
        _verify(_es256())
        assert _isolated.await_count == 1

    def test_unknown_kid_is_rejected_without_refetch_storm(self, _isolated):
        _verify(_es256())
        for _ in range(5):
            with pytest.raises(InvalidTokenError):
                _verify(_es256(kid="random-kid"))
        assert _isolated.await_count == 1

    def test_unknown_kid_refetches_after_cooldown(self, _isolated):
        _verify(_es256())
        jwt_middleware._jwks_cache["fetched_at"] -= jwt_middleware.JWKS_MIN_REFETCH_SECONDS + 1
        rotated = {**PUBLIC_JWK, "kid": "rotated"}
        _isolated.return_value = {"rotated": rotated}

        assert _verify(_es256(kid="rotated"))["sub"] == "u1"
        assert _isolated.await_count == 2

    def test_stale_keys_are_used_when_refresh_fails(self, _isolated):
        _verify(_es256())
        jwt_middleware._jwks_cache["fetched_at"] -= jwt_middleware.JWKS_TTL_SECONDS + 1
        _isolated.side_effect = Exception("network down")

        assert _verify(_es256())["sub"] == "u1"

    def test_unavailable_jwks_with_empty_cache_raises(self, _isolated):
        _isolated.side_effect = Exception("network down")
        with pytest.raises(JWKSUnavailableError):
            _verify(_es256())


class TestJWTMiddlewareEnforced:
    PROTECTED = "/api/participants/e1/participants"

    @pytest.fixture(autouse=True)
    def _middleware_on(self, monkeypatch):
        monkeypatch.delenv("TESTING", raising=False)

    def _get(self, token=None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return TestClient(app).get(self.PROTECTED, headers=headers)

    @patch("app.api.v1.participant_routes.get_event_participants")
    def test_forged_token_is_rejected_before_route(self, mock_get_participants):
        header, payload, _ = _es256().split(".")
        res = self._get(f"{header}.{payload}.forged")

        assert res.status_code == 401
        mock_get_participants.assert_not_called()

    def test_missing_token_is_rejected(self):
        assert self._get().status_code == 401

    def test_jwks_unavailable_returns_503(self, _isolated):
        _isolated.side_effect = Exception("network down")
        assert self._get(_es256()).status_code == 503

    @patch("app.api.v1.participant_routes.get_event_participants", return_value=[])
    @patch("app.core.dependencies.supabase")
    def test_valid_token_reaches_route(self, mock_sb, _):
        mock_sb.auth.get_user.return_value = SimpleNamespace(user=SimpleNamespace(id="u1"))
        res = self._get(_es256())

        assert res.status_code == 200
        assert res.json() == []

    def test_public_path_skips_verification(self, _isolated):
        TestClient(app).get("/health")
        _isolated.assert_not_awaited()
