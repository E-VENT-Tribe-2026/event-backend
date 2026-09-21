from slowapi import Limiter
from slowapi.util import get_remote_address

# Uses the client's IP address as the rate limit key.
# In-memory store is fine for a single-process deployment on Render.
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
