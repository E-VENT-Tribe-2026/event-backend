import logging
import os
import time
import httpx
from fastapi import Request
from fastapi.responses import JSONResponse
from jose import jwt, JWTError
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.config import settings

logger = logging.getLogger(__name__)

# Routes that do NOT require authentication
PUBLIC_PATHS = {
    "/",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/health",
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/forgot-password",
    "/api/auth/reset-password",
    "/api/auth/verify-reset-token",
    "/api/reminders/trigger",
}

# Route prefixes that are fully public
PUBLIC_PREFIXES = (
    "/api/events",
    "/api/recommendations",
)

ASYMMETRIC_ALGORITHMS = {"ES256", "RS256"}
JWT_AUDIENCE = "authenticated"
JWKS_TTL_SECONDS = 600
# Minimum gap between refetches triggered by an unknown kid, so forged kids can't hammer Supabase.
JWKS_MIN_REFETCH_SECONDS = 60


class InvalidTokenError(Exception):
    pass


class JWKSUnavailableError(Exception):
    pass


_jwks_cache: dict = {"keys": {}, "fetched_at": 0.0}


def _is_public(path: str) -> bool:
    if path in PUBLIC_PATHS:
        return True
    for prefix in PUBLIC_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def _supabase_auth_url() -> str:
    return f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1"


async def _fetch_jwks() -> dict:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(f"{_supabase_auth_url()}/.well-known/jwks.json")
        response.raise_for_status()
        return {key["kid"]: key for key in response.json().get("keys", []) if "kid" in key}


async def _get_signing_key(kid: str) -> dict:
    now = time.monotonic()
    age = now - _jwks_cache["fetched_at"]
    keys = _jwks_cache["keys"]

    if age > JWKS_TTL_SECONDS or (kid not in keys and age > JWKS_MIN_REFETCH_SECONDS):
        try:
            keys = await _fetch_jwks()
            _jwks_cache.update(keys=keys, fetched_at=now)
        except Exception as e:
            # Serve stale keys rather than lock everyone out during a Supabase blip.
            if not keys:
                raise JWKSUnavailableError(str(e)) from e
            logger.warning(f"JWKS refresh failed, using cached keys: {e}")

    key = keys.get(kid)
    if key is None:
        raise InvalidTokenError("Unknown signing key")
    return key


async def verify_jwt(token: str) -> dict:
    """
    Verifies signature, expiry, audience and issuer of a Supabase access token.
    Asymmetric tokens are checked against the project's JWKS; HS256 tokens
    against the legacy shared secret. Each key only accepts its own algorithm.
    """
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as e:
        raise InvalidTokenError("Malformed token") from e

    alg = header.get("alg")
    if alg in ASYMMETRIC_ALGORITHMS:
        key = await _get_signing_key(header.get("kid") or "")
        if key.get("alg", alg) != alg:
            raise InvalidTokenError("Algorithm does not match signing key")
    elif alg == "HS256":
        key = settings.SUPABASE_JWT_SECRET
    else:
        raise InvalidTokenError(f"Unsupported algorithm: {alg}")

    try:
        return jwt.decode(
            token,
            key,
            algorithms=[alg],
            audience=JWT_AUDIENCE,
            issuer=_supabase_auth_url(),
        )
    except JWTError as e:
        raise InvalidTokenError(str(e)) from e


class JWTMiddleware(BaseHTTPMiddleware):
    """
    Validates the Bearer JWT on every non-public request.
    - Verifies signature (Supabase JWKS / legacy secret), expiry, audience and issuer.
    - Rejects with 401 before the request reaches any route handler.
    - Session revocation is still checked per-route by get_current_user
      via supabase.auth.get_user().
    """

    async def dispatch(self, request: Request, call_next):
        # Skip middleware entirely in test mode
        if os.getenv("TESTING") == "true":
            return await call_next(request)

        # Always allow OPTIONS (CORS preflight) and public paths
        if request.method == "OPTIONS" or _is_public(request.url.path):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required."},
            )

        token = auth_header.removeprefix("Bearer ").strip()

        try:
            await verify_jwt(token)
        except InvalidTokenError as e:
            logger.warning(f"Rejected JWT on {request.method} {request.url.path}: {e}")
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired token."},
            )
        except JWKSUnavailableError as e:
            logger.error(f"Could not load Supabase JWKS: {e}")
            return JSONResponse(
                status_code=503,
                content={"detail": "Authentication service unavailable."},
            )

        return await call_next(request)
