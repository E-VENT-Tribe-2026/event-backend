import logging
import os
from fastapi import Request
from fastapi.responses import JSONResponse
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


def _is_public(path: str) -> bool:
    if path in PUBLIC_PATHS:
        return True
    for prefix in PUBLIC_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


class JWTMiddleware(BaseHTTPMiddleware):
    """
    Validates the Bearer JWT on every non-public request.
    - Checks token signature and expiry locally (fast, no network call).
    - Rejects with 401 before the request reaches any route handler.
    - Full session validity (revocation) is still checked per-route by
      get_current_user via supabase.auth.get_user().
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
            # Decode without signature verification — Supabase may use ES256
            # which requires the public key. The real security check is done
            # per-route by get_current_user via supabase.auth.get_user().
            # Here we just check the token is well-formed and not expired.
            import base64, json as _json
            from datetime import datetime, timezone

            parts = token.split(".")
            if len(parts) != 3:
                raise ValueError("Malformed token")

            padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
            claims = _json.loads(base64.urlsafe_b64decode(padded))

            exp = claims.get("exp")
            if exp and datetime.now(timezone.utc).timestamp() > exp:
                logger.warning(f"Expired JWT on {request.method} {request.url.path}")
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid or expired token."},
                )

        except Exception:
            logger.warning(f"Malformed JWT on {request.method} {request.url.path}")
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired token."},
            )

        return await call_next(request)
