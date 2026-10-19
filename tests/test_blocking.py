"""Ticket #184: blocking, friend request rules and event hiding, through direct API requests.

The routes and services run for real against an in-memory Supabase fake (tests/_fake_supabase.py).
Cast: A blocks B. C is a third user, D an unrelated one.
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_current_onboarded_user, get_current_user, get_optional_user
from app.main import app
from tests._fake_supabase import FakeSupabase

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
C = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
D = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"

E_A = "00000000-0000-4000-8000-00000000000a"    # organized by A, C only joined
E_B = "00000000-0000-4000-8000-00000000000b"    # organized by B
E_C = "00000000-0000-4000-8000-00000000000c"    # organized by C
E_AJ = "00000000-0000-4000-8000-0000000000aa"   # organized by A, B joined before the block
E_BJ = "00000000-0000-4000-8000-0000000000bb"   # organized by B, A joined before the block

SERVICE_MODULES = [
    "block_visibility", "block_service", "friendship_service", "profile_service", "event_service",
    "saved_event_service", "recommendation_service", "event_search_service",
    "event_details_service", "participant_service", "notification_service", "invitation_service",
]
client = TestClient(app)
HEADERS = {"Authorization": "Bearer token"}
current = {"id": None}


def _profile(uid, username):
    return {"id": uid, "username": username, "full_name": username.title(), "visibility": "public",
            "avatar_url": f"https://img/{username}.png", "avatar_kind": "photo", "icon_id": None,
            "bio": f"bio of {username}", "banner_url": f"https://img/{username}-banner.png",
            "interests": ["music"], "created_at": "2026-01-01T00:00:00+00:00",
            "interest_embedding": [0.1, 0.2]}


def _event(eid, organizer):
    return {"id": eid, "title": f"event {eid[-2:]}", "description": "d", "category": "music", "cost": 0,
            "max_capacity": 10, "status": "active", "start_datetime": "2099-01-01T10:00:00+00:00",
            "end_datetime": "2099-01-01T12:00:00+00:00", "location_name": "Berlin", "latitude": 1.0,
            "longitude": 1.0, "created_by": organizer, "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": None}


@pytest.fixture
def db():
    fake = FakeSupabase()
    fake.tables["profiles"] = [_profile(A, "alice"), _profile(B, "bob"), _profile(C, "carol"), _profile(D, "dave")]
    fake.tables["events"] = [_event(E_A, A), _event(E_B, B), _event(E_C, C), _event(E_AJ, A), _event(E_BJ, B)]
    fake.tables["event_participants"] = [
        {"user_id": A, "event_id": E_A, "status": "going"}, {"user_id": C, "event_id": E_A, "status": "going"},
        {"user_id": B, "event_id": E_B, "status": "going"}, {"user_id": C, "event_id": E_C, "status": "going"},
        {"user_id": A, "event_id": E_AJ, "status": "going"}, {"user_id": B, "event_id": E_AJ, "status": "going"},
        {"user_id": B, "event_id": E_BJ, "status": "going"}, {"user_id": A, "event_id": E_BJ, "status": "going"},
    ]
    # The RPC rows leave out created_by, like the real search_events function may.
    fake.rpc_results["search_events"] = [
        {k: v for k, v in e.items() if k != "created_by"} for e in fake.tables["events"]
    ]
    fake.tables["friendships"] = []
    fake.tables["friend_requests"] = []
    fake.tables["notifications"] = []

    def accept_friend_request(params):
        """Stands in for the database function from #210: delete the request, create the friendship."""
        rows = fake.table("friend_requests").delete().eq("id", params["p_request_id"])             .eq("receiver_id", params["p_receiver_id"]).execute().data
        if not rows:
            return []
        friendship = fake.add("friendships", {"user_id": rows[0]["initiator_id"],
                                              "friend_id": rows[0]["receiver_id"], "status": "active"})
        return [{"friendship_id": friendship["id"], "friend_since": friendship["created_at"], "created": True}]

    fake.rpc_results["accept_friend_request"] = accept_friend_request
    patches = [patch(f"app.services.{m}.supabase", fake) for m in SERVICE_MODULES]
    patches += [patch("app.services.event_service.generate_embedding", return_value=[0.1, 0.2]),
                patch("app.services.recommendation_service.generate_embedding", return_value=[0.1, 0.2])]
    for p in patches:
        p.start()
    who = lambda: SimpleNamespace(id=current["id"], email="x@y.z")
    app.dependency_overrides[get_current_user] = who
    app.dependency_overrides[get_current_onboarded_user] = who
    app.dependency_overrides[get_optional_user] = lambda: who() if current["id"] else None
    try:
        yield fake
    finally:
        for p in patches:
            p.stop()
        for dep in (get_current_user, get_current_onboarded_user, get_optional_user):
            app.dependency_overrides.pop(dep, None)
        current["id"] = None


def as_user(uid):
    current["id"] = uid


@pytest.fixture
def blocked(db):
    """A and B were friends and B had a pending request to A, then A blocks B."""
    db.add("friendships", {"user_id": A, "friend_id": B, "origin": A, "status": "active"})
    db.add("friend_requests", {"initiator_id": B, "receiver_id": A, "status": "pending"})
    db.add("notifications", {"user_id": A, "type": "friend_request_received", "related_user_id": B})
    as_user(A)
    response = client.post("/api/blocks", json={"user_id": B}, headers=HEADERS)
    assert response.status_code == 201
    return db


def ids(events):
    return {e["id"] for e in events}


# ---------------------------------------------------------------- block, unblock, list

class TestBlockEndpoints:
    def test_block_returns_the_blocked_user(self, db):
        as_user(A)
        response = client.post("/api/blocks", json={"user_id": B}, headers=HEADERS)
        assert response.status_code == 201
        body = response.json()
        assert body["user"]["id"] == B and body["user"]["username"] == "bob"
        assert body["blocked_at"]

    def test_block_removes_friendship_and_pending_requests_in_both_directions(self, db):
        db.add("friendships", {"user_id": B, "friend_id": A, "origin": B, "status": "active"})
        db.add("friend_requests", {"initiator_id": A, "receiver_id": B, "status": "pending"})
        db.add("notifications", {"user_id": B, "type": "friend_request_received", "related_user_id": A})
        as_user(A)
        client.post("/api/blocks", json={"user_id": B}, headers=HEADERS)
        assert db.tables["friendships"] == []
        assert db.tables["friend_requests"] == []

    def test_block_removes_the_pending_request_notification_and_sends_none(self, blocked):
        assert blocked.tables["notifications"] == []

    def test_block_leaves_other_friendships_alone(self, db):
        db.add("friendships", {"user_id": A, "friend_id": C, "origin": A, "status": "active"})
        as_user(A)
        client.post("/api/blocks", json={"user_id": B}, headers=HEADERS)
        assert len(db.tables["friendships"]) == 1

    def test_blocking_twice_is_safe(self, db):
        as_user(A)
        assert client.post("/api/blocks", json={"user_id": B}, headers=HEADERS).status_code == 201
        assert client.post("/api/blocks", json={"user_id": B}, headers=HEADERS).status_code == 201
        assert len(db.tables["user_blocks"]) == 1

    def test_cannot_block_yourself(self, db):
        as_user(A)
        response = client.post("/api/blocks", json={"user_id": A}, headers=HEADERS)
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "cannot_block_self"

    def test_cannot_block_unknown_user(self, db):
        as_user(A)
        response = client.post("/api/blocks", json={"user_id": "99999999-9999-4999-8999-999999999999"}, headers=HEADERS)
        assert response.status_code == 404

    def test_blocking_keeps_participation_and_events(self, blocked):
        pairs = {(p["user_id"], p["event_id"]) for p in blocked.tables["event_participants"]}
        assert (B, E_AJ) in pairs and (A, E_BJ) in pairs
        assert len(blocked.tables["events"]) == 5

    def test_unblock_does_not_restore_the_friendship(self, blocked):
        as_user(A)
        assert client.delete(f"/api/blocks/{B}", headers=HEADERS).status_code == 200
        assert client.get("/api/friends", headers=HEADERS).json()["data"] == []
        assert blocked.tables["user_blocks"] == []

    def test_unblock_of_a_user_not_blocked_is_404(self, db):
        as_user(A)
        assert client.delete(f"/api/blocks/{B}", headers=HEADERS).status_code == 404

    def test_a_user_cannot_unblock_for_someone_else(self, blocked):
        as_user(B)
        assert client.delete(f"/api/blocks/{B}", headers=HEADERS).status_code == 404
        assert client.delete(f"/api/blocks/{A}", headers=HEADERS).status_code == 404
        assert len(blocked.tables["user_blocks"]) == 1

    def test_list_is_paged_newest_first_with_name_username_and_picture(self, blocked):
        client.post("/api/blocks", json={"user_id": C}, headers=HEADERS)
        first = client.get("/api/blocks?limit=1", headers=HEADERS).json()
        assert first["has_more"] is True and first["page"] == 1
        assert first["data"][0]["user"]["id"] == C
        second = client.get("/api/blocks?limit=1&page=2", headers=HEADERS).json()
        assert second["has_more"] is False
        user = second["data"][0]["user"]
        assert (user["id"], user["username"], user["full_name"], user["avatar_url"]) == \
            (B, "bob", "Bob", "https://img/bob.png")

    def test_list_only_shows_my_own_blocks(self, blocked):
        as_user(B)
        assert client.get("/api/blocks", headers=HEADERS).json()["data"] == []


# ---------------------------------------------------------------- friend requests

class TestFriendRequests:
    def test_blocked_user_cannot_send_a_friend_request(self, blocked):
        as_user(B)
        response = client.post("/api/friends/requests", json={"receiver_id": A}, headers=HEADERS)
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "user_not_found"
        assert blocked.tables["friend_requests"] == []
        assert blocked.tables["notifications"] == []

    def test_blocking_user_cannot_send_one_either_until_unblocking(self, blocked):
        as_user(A)
        response = client.post("/api/friends/requests", json={"receiver_id": B}, headers=HEADERS)
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "user_blocked"
        client.delete(f"/api/blocks/{B}", headers=HEADERS)
        assert client.post("/api/friends/requests", json={"receiver_id": B}, headers=HEADERS).status_code == 201

    def test_unrelated_user_can_still_send_a_request(self, blocked):
        as_user(B)
        assert client.post("/api/friends/requests", json={"receiver_id": C}, headers=HEADERS).status_code == 201

    @pytest.fixture
    def pending(self, db):
        row = db.add("friend_requests", {"initiator_id": C, "receiver_id": D, "status": "pending"})
        return row["id"]

    def test_only_the_receiver_can_accept(self, db, pending):
        for uid, expected in ((C, 403), (A, 404)):
            as_user(uid)
            assert client.post(f"/api/friends/requests/{pending}/accept", headers=HEADERS).status_code == expected
        assert len(db.tables["friend_requests"]) == 1 and db.tables["friendships"] == []
        as_user(D)
        assert client.post(f"/api/friends/requests/{pending}/accept", headers=HEADERS).status_code == 200
        assert len(db.tables["friendships"]) == 1

    def test_only_the_receiver_can_decline(self, db, pending):
        for uid, expected in ((C, 403), (A, 404)):
            as_user(uid)
            assert client.post(f"/api/friends/requests/{pending}/decline", headers=HEADERS).status_code == expected
        assert len(db.tables["friend_requests"]) == 1
        as_user(D)
        assert client.post(f"/api/friends/requests/{pending}/decline", headers=HEADERS).status_code == 200

    def test_only_the_sender_can_cancel(self, db, pending):
        for uid, expected in ((D, 403), (A, 404)):
            as_user(uid)
            assert client.delete(f"/api/friends/requests/{pending}", headers=HEADERS).status_code == expected
        assert len(db.tables["friend_requests"]) == 1
        as_user(C)
        assert client.delete(f"/api/friends/requests/{pending}", headers=HEADERS).status_code == 200

    def test_a_request_removed_by_a_block_cannot_be_accepted(self, db):
        row = db.add("friend_requests", {"initiator_id": B, "receiver_id": A, "status": "pending"})
        as_user(A)
        client.post("/api/blocks", json={"user_id": B}, headers=HEADERS)
        assert client.post(f"/api/friends/requests/{row['id']}/accept", headers=HEADERS).status_code == 404


# ---------------------------------------------------------------- profile, search, suggestions

class TestProfileSearchSuggestions:
    def test_blocked_user_cannot_view_the_blocking_users_profile(self, blocked):
        as_user(B)
        response = client.get(f"/api/profile/{A}", headers=HEADERS)
        assert response.status_code == 404
        assert response.json()["detail"] == {"code": "profile_unavailable", "message": "This profile is unavailable."}

    def test_blocking_user_sees_only_the_top_of_the_profile(self, blocked):
        as_user(A)
        body = client.get(f"/api/profile/{B}", headers=HEADERS).json()
        assert body["blocked_by_me"] is True
        assert body["username"] == "bob" and body["full_name"] == "Bob" and body["bio"] == "bio of bob"
        assert body["avatar_url"] == "https://img/bob.png" and body["interests"] == ["music"]
        assert body["banner_url"] == "https://img/bob-banner.png"
        assert "events" not in body and "friendship" not in body and "friends" not in body

    def test_other_profiles_still_open_with_events_and_friendship(self, blocked):
        as_user(B)
        body = client.get(f"/api/profile/{C}", headers=HEADERS).json()
        assert body["blocked_by_me"] is False and "events" in body and "friendship" in body
        as_user(D)
        assert client.get(f"/api/profile/{A}", headers=HEADERS).status_code == 200

    def test_profile_comes_back_after_unblocking(self, blocked):
        as_user(A)
        client.delete(f"/api/blocks/{B}", headers=HEADERS)
        as_user(B)
        assert client.get(f"/api/profile/{A}", headers=HEADERS).status_code == 200

    def test_search_hides_the_blocking_user_from_the_blocked_user(self, blocked):
        as_user(B)
        assert client.get("/api/profile/search?q=ali", headers=HEADERS).json()["data"] == []
        as_user(D)
        assert len(client.get("/api/profile/search?q=ali", headers=HEADERS).json()["data"]) == 1

    def test_blocking_user_can_still_find_the_blocked_user(self, blocked):
        as_user(A)
        found = client.get("/api/profile/search?q=bo", headers=HEADERS).json()["data"]
        assert [p["id"] for p in found] == [B]

    def test_suggestions_leave_out_the_blocking_user(self, blocked):
        as_user(B)
        suggested = {i["user"]["id"] for i in client.get("/api/friends/suggestions", headers=HEADERS).json()["data"]}
        assert A not in suggested and {C, D} <= suggested

    def test_suggestions_rank_nearest_neighbors_first(self, db):
        as_user(B)
        for row in db.tables["profiles"]:
            if row["id"] == B:
                row["interest_embedding"] = [1.0, 0.0]
            elif row["id"] == A:
                row["interest_embedding"] = [1.0, 0.0]
            elif row["id"] == D:
                row["interest_embedding"] = [0.8, 0.2]
            else:
                row["interest_embedding"] = [0.0, 1.0]
        ids = [i["user"]["id"] for i in client.get("/api/friends/suggestions", headers=HEADERS).json()["data"]]
        assert ids == [A, D, C]


# ---------------------------------------------------------------- events

class TestEventHiding:
    def test_event_list_for_the_home_page_and_the_map(self, blocked):
        as_user(B)
        shown = ids(client.get("/api/events/?limit=50", headers=HEADERS).json()["data"])
        assert E_A not in shown
        assert {E_B, E_C, E_AJ, E_BJ} <= shown          # joined before the block, own, and others'
        as_user(A)
        shown = ids(client.get("/api/events/?limit=50", headers=HEADERS).json()["data"])
        assert E_B not in shown
        assert {E_A, E_C, E_AJ, E_BJ} <= shown

    def test_event_list_with_filters_used_by_the_map(self, blocked):
        as_user(B)
        shown = ids(client.get("/api/events/?upcoming=true&category=music&limit=50", headers=HEADERS).json()["data"])
        assert E_A not in shown and E_C in shown

    def test_event_list_pagination_is_not_shortened_by_hidden_events(self, blocked):
        as_user(B)
        first = client.get("/api/events/?limit=2&page=1", headers=HEADERS).json()["data"]
        second = client.get("/api/events/?limit=2&page=2", headers=HEADERS).json()["data"]
        assert len(first) == 2 and len(second) == 2 and E_A not in ids(first + second)

    def test_visitors_without_a_token_see_every_event(self, blocked):
        as_user(None)
        assert E_A in ids(client.get("/api/events/?limit=50").json()["data"])
        assert client.get(f"/api/events/{E_A}").status_code == 200

    def test_event_search(self, blocked):
        as_user(B)
        shown = ids(client.get("/api/events/?search=event&limit=10", headers=HEADERS).json()["data"])
        assert E_A not in shown and E_C in shown
        as_user(A)
        assert E_B not in ids(client.get("/api/events/?search=event&limit=10", headers=HEADERS).json()["data"])

    def test_assistant_event_search_and_details(self, blocked):
        from app.services.event_details_service import get_event_details
        from app.services.event_search_service import search_events
        assert E_A not in ids(search_events({"upcoming": False}, B)["events"])
        assert E_A in ids(search_events({"upcoming": False}, D)["events"])
        assert get_event_details({"event_id": E_A}, B)["error"]["code"] == "NOT_FOUND"
        assert get_event_details({"event_id": E_AJ}, B)["success"] is True

    def test_recommendations(self, blocked):
        as_user(B)
        shown = ids(client.get("/api/recommendations", headers=HEADERS).json()["data"])
        assert E_A not in shown and shown == {E_C}
        as_user(A)
        assert ids(client.get("/api/recommendations", headers=HEADERS).json()["data"]) == {E_C}

    def test_event_details_answer_not_found(self, blocked):
        as_user(B)
        response = client.get(f"/api/events/{E_A}", headers=HEADERS)
        assert response.status_code == 404 and response.json()["detail"] == "Event not found"
        assert client.get(f"/api/events/{E_C}", headers=HEADERS).status_code == 200
        as_user(A)
        assert client.get(f"/api/events/{E_B}", headers=HEADERS).status_code == 404

    def test_events_joined_before_the_block_still_open(self, blocked):
        as_user(B)
        assert client.get(f"/api/events/{E_AJ}", headers=HEADERS).status_code == 200
        as_user(A)
        assert client.get(f"/api/events/{E_BJ}", headers=HEADERS).status_code == 200

    def test_event_details_open_again_after_unblocking(self, blocked):
        as_user(A)
        client.delete(f"/api/blocks/{B}", headers=HEADERS)
        assert client.get(f"/api/events/{E_B}", headers=HEADERS).status_code == 200

    def test_another_users_profile_events(self, blocked):
        def seen(viewer):
            as_user(viewer)
            events = client.get(f"/api/profile/{C}", headers=HEADERS).json()["events"]
            return ids(events["organized"]["upcoming"]), ids(events["joined"]["upcoming"])

        # C organized E_C and only joined E_A, which A organizes.
        assert seen(B) == ({E_C}, set())
        assert seen(D) == ({E_C}, {E_A})
        assert seen(A) == ({E_C}, {E_A})

    def test_favourites(self, blocked):
        for uid, event in ((B, E_A), (B, E_C), (B, E_AJ), (A, E_B), (A, E_C)):
            blocked.add("saved_events", {"user_id": uid, "event_id": event})
        as_user(B)
        assert ids(client.get("/api/favorites/all", headers=HEADERS).json()) == {E_C, E_AJ}
        as_user(A)
        assert ids(client.get("/api/favorites/all", headers=HEADERS).json()) == {E_C}

    def test_a_hidden_event_cannot_be_joined(self, blocked):
        as_user(B)
        assert client.post(f"/api/participants/{E_A}/join", headers=HEADERS).status_code == 404

    def test_a_hidden_event_does_not_list_friends_attending(self, blocked):
        as_user(B)
        assert client.get(f"/api/participants/{E_A}/participants/friends", headers=HEADERS).status_code == 404
        assert client.get(f"/api/participants/{E_C}/participants/friends", headers=HEADERS).status_code == 200

    def test_unrelated_users_see_everything(self, blocked):
        as_user(D)
        shown = ids(client.get("/api/events/?limit=50", headers=HEADERS).json()["data"])
        assert shown == {E_A, E_B, E_C, E_AJ, E_BJ}

    def test_events_in_the_list_carry_friends_attending_count(self, blocked):
        as_user(B)
        data = client.get("/api/events/?limit=50", headers=HEADERS).json()["data"]
        assert E_A not in ids(data) and all("friends_attending_count" in e for e in data)
