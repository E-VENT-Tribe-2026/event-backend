# conftest.py  ← sits next to app/ and tests/
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

# Tell JWTMiddleware to skip token validation during tests
os.environ.setdefault("TESTING", "true")
