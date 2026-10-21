import threading
import time
from collections import defaultdict, deque

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from app.core.dependencies import require_regular_user

# Per signed-in user (not per IP). In-memory, like app.core.limiter: fine for a single-process deployment.
# The Friends tab searches on every typing pause (debounced) and loads more pages on scroll,
# so the search limit leaves room for roughly one request per second for a full minute.
SEARCH_LIMIT = 60
FRIEND_REQUEST_LIMIT = 30
WINDOW_SECONDS = 60

_hits: dict[tuple[str, str], deque] = defaultdict(deque)
_lock = threading.Lock()


class UserRateLimitExceeded(Exception):
    def __init__(self, limit: int, window: int, retry_after: int):
        self.limit = limit
        self.window = window
        self.retry_after = retry_after


def reset_user_rate_limits() -> None:
    with _lock:
        _hits.clear()


def user_rate_limit(scope: str, limit: int, window: int = WINDOW_SECONDS, user_dep=require_regular_user):
    """Dependency factory: sliding-window limit of `limit` requests per `window` seconds per user."""

    def dependency(user=Depends(user_dep)):
        now = time.monotonic()
        with _lock:
            hits = _hits[(scope, str(user.id))]
            while hits and now - hits[0] >= window:
                hits.popleft()
            if len(hits) >= limit:
                retry_after = max(1, int(window - (now - hits[0])) + 1)
                raise UserRateLimitExceeded(limit, window, retry_after)
            hits.append(now)
        return user

    return dependency


async def user_rate_limit_handler(request: Request, exc: UserRateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Too many requests. Please wait a moment and try again.",
            "code": "rate_limit_exceeded",
            "retry_after": exc.retry_after,
        },
        headers={"Retry-After": str(exc.retry_after)},
    )
