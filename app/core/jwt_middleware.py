import logging
import os
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from jose import jwt, JWTError
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
            jwt.decode(
                token,
                settings.SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                options={"verify_aud": False},
            )
        except JWTError:
            logger.warning(f"Invalid JWT on {request.method} {request.url.path}")
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired token."},
            )

        return await call_next(request)
