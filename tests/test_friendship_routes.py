import pytest
from urllib.parse import quote
from fastapi import HTTPException
from fastapi.testclient import TestClient
from unittest.mock import patch
from app.main import app
from app.core.dependencies import get_current_user

client = TestClient(app)
HEADERS = {"Authorization": "Bearer token"}
OTHER = "22222222-2222-4222-8222-222222222222"


JANE = {"id": OTHER, "username": "jane_doe", "full_name": None, "display_name": None,
        "avatar_kind": "icon", "icon_id": None, "avatar_url": None}


class MockUser:
    id = "u1"
    email = "test@test.com"


@pytest.fixture(autouse=True)
def _auth_override():
    app.dependency_overrides[get_current_user] = lambda: MockUser()
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_user, None)


class TestFriendRequestRoutes:
    @patch("app.api.v1.friendship_routes.send_friend_request")
    def test_post_send_request(self, mock_send):
        payload = {"request_id": 7, "created_at": "2026-01-01T10:00:00+00:00",
                   "user": JANE}
        mock_send.return_value = payload
        response = client.post("/api/friends/requests", json={"receiver_id": OTHER}, headers=HEADERS)
        assert response.status_code == 201
        assert response.json()["request_id"] == 7
        assert response.json()["user"]["username"] == "jane_doe"
        mock_send.assert_called_once_with("u1", OTHER)

    def test_post_send_request_without_body_returns_422(self):
        response = client.post("/api/friends/requests", headers=HEADERS)
        assert response.status_code == 422

    def test_post_send_request_non_uuid_returns_422(self):
        response = client.post("/api/friends/requests", json={"receiver_id": "not-a-uuid"}, headers=HEADERS)
        assert response.status_code == 422

    @patch("app.api.v1.friendship_routes.get_incoming_requests")
    def test_get_incoming_defaults(self, mock_get):
        body = {"page": 1, "limit": 20, "has_more": False, "data": []}
        mock_get.return_value = body
        response = client.get("/api/friends/requests/incoming", headers=HEADERS)
        assert response.status_code == 200
        assert response.json() == body
        mock_get.assert_called_once_with("u1", 1, 20)

    @patch("app.api.v1.friendship_routes.get_incoming_requests")
    def test_get_incoming_custom_paging(self, mock_get):
        mock_get.return_value = {"page": 3, "limit": 5, "has_more": True, "data": []}
        response = client.get("/api/friends/requests/incoming?page=3&limit=5", headers=HEADERS)
        assert response.status_code == 200
        mock_get.assert_called_once_with("u1", 3, 5)

    @patch("app.api.v1.friendship_routes.get_sent_requests")
    def test_get_sent_defaults(self, mock_get):
        body = {"page": 1, "limit": 20, "has_more": False, "data": []}
        mock_get.return_value = body
        response = client.get("/api/friends/requests/sent", headers=HEADERS)
        assert response.status_code == 200
        assert response.json() == body
        mock_get.assert_called_once_with("u1", 1, 20)

    @patch("app.api.v1.friendship_routes.count_incoming_requests")
    def test_get_count(self, mock_count):
        mock_count.return_value = {"count": 4}
        response = client.get("/api/friends/requests/count", headers=HEADERS)
        assert response.status_code == 200
        assert response.json() == {"count": 4}
        mock_count.assert_called_once_with("u1")

    @patch("app.api.v1.friendship_routes.accept_friend_request")
    def test_post_accept(self, mock_accept):
        body = {"friend_since": "2026-02-02T10:00:00+00:00",
                "user": JANE}
        mock_accept.return_value = body
        response = client.post("/api/friends/requests/7/accept", headers=HEADERS)
        assert response.status_code == 200
        assert response.json() == body
        mock_accept.assert_called_once_with(7, "u1")

    @patch("app.api.v1.friendship_routes.decline_friend_request")
    def test_post_decline(self, mock_decline):
        mock_decline.return_value = {"message": "Friend request declined"}
        response = client.post("/api/friends/requests/7/decline", headers=HEADERS)
        assert response.status_code == 200
        assert response.json() == {"message": "Friend request declined"}
        mock_decline.assert_called_once_with(7, "u1")

    @patch("app.api.v1.friendship_routes.cancel_friend_request")
    def test_delete_cancel(self, mock_cancel):
        mock_cancel.return_value = {"message": "Friend request cancelled"}
        response = client.delete("/api/friends/requests/7", headers=HEADERS)
        assert response.status_code == 200
        assert response.json() == {"message": "Friend request cancelled"}
        mock_cancel.assert_called_once_with(7, "u1")

    @pytest.mark.parametrize("method,path,target", [
        ("post", "/requests/0/accept", "accept_friend_request"),
        ("post", f"/requests/{2**63}/accept", "accept_friend_request"),
        ("post", "/requests/0/decline", "decline_friend_request"),
        ("post", f"/requests/{2**63}/decline", "decline_friend_request"),
        ("delete", "/requests/0", "cancel_friend_request"),
        ("delete", f"/requests/{2**63}", "cancel_friend_request"),
    ])
    def test_request_id_out_of_range_returns_422(self, method, path, target):
        with patch(f"app.api.v1.friendship_routes.{target}") as mock_svc:
            response = getattr(client, method)(f"/api/friends{path}", headers=HEADERS)
        assert response.status_code == 422
        mock_svc.assert_not_called()

    @pytest.mark.parametrize("path,target", [
        ("/requests/incoming", "get_incoming_requests"),
        ("/requests/sent", "get_sent_requests"),
        ("", "get_friends"),
    ])
    def test_page_above_max_returns_422(self, path, target):
        with patch(f"app.api.v1.friendship_routes.{target}") as mock_svc:
            response = client.get(f"/api/friends{path}?page=10001", headers=HEADERS)
        assert response.status_code == 422
        mock_svc.assert_not_called()

    def test_non_integer_request_id_returns_422(self):
        response = client.post("/api/friends/requests/abc/accept", headers=HEADERS)
        assert response.status_code == 422


class TestFriendsRoutes:
    @patch("app.api.v1.friendship_routes.get_friends")
    def test_get_friends_defaults(self, mock_get):
        body = {"page": 1, "limit": 20, "has_more": False, "data": [
            {"friend_since": "2026-02-02T10:00:00+00:00",
             "user": JANE}]}
        mock_get.return_value = body
        response = client.get("/api/friends", headers=HEADERS)
        assert response.status_code == 200
        assert response.json() == body
        mock_get.assert_called_once_with("u1", 1, 20)

    @patch("app.api.v1.friendship_routes.get_friends")
    def test_get_friends_limit_above_max_returns_422(self, mock_get):
        response = client.get("/api/friends?limit=51", headers=HEADERS)
        assert response.status_code == 422
        mock_get.assert_not_called()

    @patch("app.api.v1.friendship_routes.get_incoming_requests")
    def test_incoming_limit_above_max_returns_422(self, mock_get):
        response = client.get("/api/friends/requests/incoming?limit=51", headers=HEADERS)
        assert response.status_code == 422
        mock_get.assert_not_called()

    @patch("app.api.v1.friendship_routes.remove_friend")
    def test_delete_friend(self, mock_remove):
        mock_remove.return_value = {"message": "Friend removed"}
        response = client.delete(f"/api/friends/{OTHER}", headers=HEADERS)
        assert response.status_code == 200
        assert response.json() == {"message": "Friend removed"}
        mock_remove.assert_called_once_with("u1", OTHER)

    @patch("app.api.v1.friendship_routes.remove_friend")
    def test_delete_friend_crafted_filter_returns_422(self, mock_remove):
        crafted = quote("x),user_id.not.is.null,and(user_id.eq.x", safe="")
        response = client.delete(f"/api/friends/{crafted}", headers=HEADERS)
        assert response.status_code == 422
        mock_remove.assert_not_called()

    @patch("app.api.v1.friendship_routes.remove_friend")
    def test_delete_friend_non_uuid_returns_422(self, mock_remove):
        response = client.delete("/api/friends/not-a-uuid", headers=HEADERS)
        assert response.status_code == 422
        mock_remove.assert_not_called()

    @patch("app.api.v1.friendship_routes.remove_friend")
    def test_delete_requests_collection_returns_422(self, mock_remove):
        response = client.delete("/api/friends/requests", headers=HEADERS)
        assert response.status_code == 422
        mock_remove.assert_not_called()


class TestFriendErrorPassthrough:
    @patch("app.api.v1.friendship_routes.send_friend_request")
    def test_service_error_detail_is_unchanged(self, mock_send):
        detail = {"code": "request_already_received",
                  "message": "This user has already sent you a friend request.",
                  "request_id": 42}
        mock_send.side_effect = HTTPException(409, detail=detail)
        response = client.post("/api/friends/requests", json={"receiver_id": OTHER}, headers=HEADERS)
        assert response.status_code == 409
        assert response.json() == {"detail": detail}


class TestAuthRequired:
    @pytest.mark.parametrize("method,path,target,kwargs", [
        ("post", "/requests", "send_friend_request", {"json": {"receiver_id": OTHER}}),
        ("get", "/requests/incoming", "get_incoming_requests", {}),
        ("get", "/requests/sent", "get_sent_requests", {}),
        ("get", "/requests/count", "count_incoming_requests", {}),
        ("post", "/requests/7/accept", "accept_friend_request", {}),
        ("post", "/requests/7/decline", "decline_friend_request", {}),
        ("delete", "/requests/7", "cancel_friend_request", {}),
        ("get", "", "get_friends", {}),
        ("delete", f"/{OTHER}", "remove_friend", {}),
    ])
    def test_unauthenticated_is_rejected(self, method, path, target, kwargs):
        app.dependency_overrides.pop(get_current_user, None)
        assert get_current_user not in app.dependency_overrides
        with patch(f"app.api.v1.friendship_routes.{target}") as mock_svc:
            response = getattr(client, method)(f"/api/friends{path}", **kwargs)
        assert response.status_code in (401, 403)
        mock_svc.assert_not_called()
