import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from app.main import app
from app.core.dependencies import get_current_user, require_regular_user
from app.core import user_rate_limit as url
from app.core.user_rate_limit import SEARCH_LIMIT, FRIEND_REQUEST_LIMIT

client = TestClient(app)
HEADERS = {"Authorization": "Bearer token"}
OTHER = "22222222-2222-4222-8222-222222222222"


class MockUser:
    def __init__(self, user_id):
        self.id = user_id
        self.email = f"{user_id}@test.com"


@pytest.fixture
def as_user():
    def _as(user_id):
        user = MockUser(user_id)
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[require_regular_user] = lambda: user
    yield _as
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(require_regular_user, None)


EMPTY_PAGE = {"page": 1, "limit": 10, "has_more": False, "data": []}
SENT = {"request_id": 1, "created_at": "2026-01-01T00:00:00Z", "user": {"id": OTHER, "username": "jane_doe", "full_name": None, "display_name": None, "avatar_kind": "icon", "icon_id": None, "avatar_url": None}}


class TestSearchRateLimit:
    @patch("app.api.v1.profile_routes.search_profiles", return_value=EMPTY_PAGE)
    def test_normal_typing_and_load_more_is_not_refused(self, _search, as_user):
        as_user("u1")
        for i in range(SEARCH_LIMIT):
            assert client.get(f"/api/profile/search?q=a&page={i % 5 + 1}", headers=HEADERS).status_code == 200

    @patch("app.api.v1.profile_routes.search_profiles", return_value=EMPTY_PAGE)
    def test_over_limit_is_refused_with_clear_response(self, _search, as_user):
        as_user("u1")
        for _ in range(SEARCH_LIMIT):
            client.get("/api/profile/search?q=a", headers=HEADERS)
        response = client.get("/api/profile/search?q=a", headers=HEADERS)
        assert response.status_code == 429
        body = response.json()
        assert body["code"] == "rate_limit_exceeded"
        assert isinstance(body["detail"], str)
        assert body["retry_after"] >= 1
        assert response.headers["Retry-After"] == str(body["retry_after"])

    @patch("app.api.v1.profile_routes.search_profiles", return_value=EMPTY_PAGE)
    def test_limit_is_per_user(self, _search, as_user):
        as_user("u1")
        for _ in range(SEARCH_LIMIT + 1):
            client.get("/api/profile/search?q=a", headers=HEADERS)
        as_user("u2")
        assert client.get("/api/profile/search?q=a", headers=HEADERS).status_code == 200

    @patch("app.api.v1.profile_routes.search_profiles", return_value=EMPTY_PAGE)
    def test_window_expires(self, _search, as_user):
        as_user("u1")
        with patch("app.core.user_rate_limit.time.monotonic", return_value=1000.0):
            for _ in range(SEARCH_LIMIT):
                client.get("/api/profile/search?q=a", headers=HEADERS)
            assert client.get("/api/profile/search?q=a", headers=HEADERS).status_code == 429
        with patch("app.core.user_rate_limit.time.monotonic", return_value=1000.0 + url.WINDOW_SECONDS + 1):
            assert client.get("/api/profile/search?q=a", headers=HEADERS).status_code == 200


class TestFriendRequestRateLimit:
    @patch("app.api.v1.friendship_routes.send_friend_request", return_value=SENT)
    def test_over_limit_is_refused(self, _send, as_user):
        as_user("u1")
        for _ in range(FRIEND_REQUEST_LIMIT):
            client.post("/api/friends/requests", json={"receiver_id": OTHER}, headers=HEADERS)
        response = client.post("/api/friends/requests", json={"receiver_id": OTHER}, headers=HEADERS)
        assert response.status_code == 429
        assert response.json()["code"] == "rate_limit_exceeded"
        _send.assert_called()
        assert _send.call_count == FRIEND_REQUEST_LIMIT

    @patch("app.api.v1.friendship_routes.send_friend_request", return_value=SENT)
    def test_limit_is_per_user(self, _send, as_user):
        as_user("u1")
        for _ in range(FRIEND_REQUEST_LIMIT + 1):
            client.post("/api/friends/requests", json={"receiver_id": OTHER}, headers=HEADERS)
        as_user("u2")
        response = client.post("/api/friends/requests", json={"receiver_id": OTHER}, headers=HEADERS)
        assert response.status_code != 429
