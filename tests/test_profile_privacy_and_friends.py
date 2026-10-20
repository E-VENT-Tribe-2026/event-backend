import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.core.dependencies import get_current_user, get_current_onboarded_user

client = TestClient(app)

TARGET_USER_ID = "11111111-1111-1111-1111-111111111111"
FRIEND_USER_ID = "22222222-2222-2222-2222-222222222222"
NON_FRIEND_USER_ID = "33333333-3333-3333-3333-333333333333"
FRIEND_ITEM_ID = "44444444-4444-4444-4444-444444444444"


class MockUser:
    def __init__(self, user_id):
        self.id = user_id
        self.email = f"{user_id}@example.com"


@pytest.fixture
def target_profile_public():
    return {
        "id": TARGET_USER_ID,
        "username": "alex",
        "full_name": "Alex Smith",
        "avatar_url": "https://example.com/avatar.jpg",
        "avatar_kind": "photo",
        "icon_id": None,
        "banner_url": "https://example.com/banner.jpg",
        "banner": "https://example.com/banner.jpg",
        "bio": "Adventurer and coder",
        "interests": ["hiking", "gaming"],
        "visibility": "public",
        "created_at": "2026-01-01T00:00:00Z",
    }


@pytest.fixture
def target_profile_friends_only():
    return {
        "id": TARGET_USER_ID,
        "username": "alex",
        "full_name": "Alex Smith",
        "avatar_url": "https://example.com/avatar.jpg",
        "avatar_kind": "photo",
        "icon_id": None,
        "banner_url": "https://example.com/banner.jpg",
        "banner": "https://example.com/banner.jpg",
        "bio": "Adventurer and coder",
        "interests": ["hiking", "gaming"],
        "visibility": "friends_only",
        "created_at": "2026-01-01T00:00:00Z",
    }


@pytest.fixture
def sample_events():
    return {
        "organized": {
            "upcoming": [{"id": "e1", "title": "Upcoming Hike", "status": "active"}],
            "past": [{"id": "e2", "title": "Past Hackathon", "status": "active"}],
        },
        "joined": {
            "upcoming": [{"id": "e3", "title": "Upcoming Board Game", "status": "active"}],
            "past": [{"id": "e4", "title": "Past Concert", "status": "active"}],
        },
    }


@pytest.fixture
def sample_friends_page():
    return {
        "page": 1,
        "limit": 10,
        "has_more": False,
        "data": [
            {
                "id": FRIEND_ITEM_ID,
                "username": "sam",
                "full_name": "Sam Taylor",
                "display_name": "sam",
                "avatar_kind": "icon",
                "icon_id": "user",
                "avatar_url": None,
            }
        ],
    }


class TestProfileUpdateVisibility:
    """Test updating profile visibility via PUT /api/profile/me."""

    @patch("app.api.v1.profile_routes.update_profile")
    def test_update_visibility_public_accepted(self, mock_update):
        app.dependency_overrides[get_current_onboarded_user] = lambda: MockUser("u1")
        try:
            mock_update.return_value = {"id": "u1", "visibility": "public"}
            resp = client.put(
                "/api/profile/me",
                json={"visibility": "public"},
                headers={"Authorization": "Bearer token"},
            )
            assert resp.status_code == 200
            assert resp.json()["visibility"] == "public"
            mock_update.assert_called_once_with("u1", {"visibility": "public"})
        finally:
            app.dependency_overrides.pop(get_current_onboarded_user, None)

    @patch("app.api.v1.profile_routes.update_profile")
    def test_update_visibility_friends_only_accepted(self, mock_update):
        app.dependency_overrides[get_current_onboarded_user] = lambda: MockUser("u1")
        try:
            mock_update.return_value = {"id": "u1", "visibility": "friends_only"}
            resp = client.put(
                "/api/profile/me",
                json={"visibility": "friends_only"},
                headers={"Authorization": "Bearer token"},
            )
            assert resp.status_code == 200
            assert resp.json()["visibility"] == "friends_only"
            mock_update.assert_called_once_with("u1", {"visibility": "friends_only"})
        finally:
            app.dependency_overrides.pop(get_current_onboarded_user, None)

    def test_update_visibility_other_value_refused(self):
        app.dependency_overrides[get_current_onboarded_user] = lambda: MockUser("u1")
        try:
            for invalid_val in ("private", "hidden", "anyone", "FOO"):
                resp = client.put(
                    "/api/profile/me",
                    json={"visibility": invalid_val},
                    headers={"Authorization": "Bearer token"},
                )
                assert resp.status_code == 422
        finally:
            app.dependency_overrides.pop(get_current_onboarded_user, None)


class TestPublicProfileContextualView:
    """Test what different viewers receive when viewing a profile."""

    @patch("app.services.public_profile_service.get_public_profile")
    @patch("app.services.public_profile_service.get_profile_events")
    @patch("app.services.public_profile_service.get_friendship_state")
    @patch("app.services.public_profile_service.get_user_friends_summary_page")
    def test_public_profile_seen_by_friend(
        self, mock_friends, mock_state, mock_events, mock_profile,
        target_profile_public, sample_events, sample_friends_page
    ):
        mock_profile.return_value = dict(target_profile_public)
        mock_events.return_value = dict(sample_events)
        mock_state.return_value = {"status": "friends", "request_id": None}
        mock_friends.return_value = sample_friends_page

        from app.services.public_profile_service import build_public_profile
        result = build_public_profile(TARGET_USER_ID, FRIEND_USER_ID)

        # Friend sees everything
        assert result["username"] == "alex"
        assert result["full_name"] == "Alex Smith"
        assert result["bio"] == "Adventurer and coder"
        assert result["interests"] == ["hiking", "gaming"]
        assert result["banner_url"] == "https://example.com/banner.jpg"
        assert len(result["friends"]) == 1
        assert len(result["events"]["organized"]["upcoming"]) == 1
        assert len(result["events"]["organized"]["past"]) == 1
        assert len(result["events"]["joined"]["upcoming"]) == 1
        assert len(result["events"]["joined"]["past"]) == 1
        assert result["friendship"]["status"] == "friends"

    @patch("app.services.public_profile_service.get_public_profile")
    @patch("app.services.public_profile_service.get_profile_events")
    @patch("app.services.public_profile_service.get_friendship_state")
    @patch("app.services.public_profile_service.get_user_friends_summary_page")
    def test_public_profile_seen_by_non_friend(
        self, mock_friends, mock_state, mock_events, mock_profile,
        target_profile_public, sample_events, sample_friends_page
    ):
        mock_profile.return_value = dict(target_profile_public)
        import copy
        mock_events.return_value = copy.deepcopy(sample_events)
        mock_state.return_value = {"status": "none", "request_id": None}
        mock_friends.return_value = sample_friends_page

        from app.services.public_profile_service import build_public_profile
        result = build_public_profile(TARGET_USER_ID, NON_FRIEND_USER_ID)

        # Non-friend sees bio, interests, friends, and past events, but NO upcoming events
        assert result["username"] == "alex"
        assert result["full_name"] == "Alex Smith"
        assert result["bio"] == "Adventurer and coder"
        assert result["interests"] == ["hiking", "gaming"]
        assert len(result["friends"]) == 1
        assert result["events"]["organized"]["upcoming"] == []
        assert result["events"]["joined"]["upcoming"] == []
        assert len(result["events"]["organized"]["past"]) == 1
        assert len(result["events"]["joined"]["past"]) == 1

    @patch("app.services.public_profile_service.get_public_profile")
    @patch("app.services.public_profile_service.get_profile_events")
    @patch("app.services.public_profile_service.get_friendship_state")
    @patch("app.services.public_profile_service.get_user_friends_summary_page")
    def test_friends_only_profile_seen_by_friend(
        self, mock_friends, mock_state, mock_events, mock_profile,
        target_profile_friends_only, sample_events, sample_friends_page
    ):
        mock_profile.return_value = dict(target_profile_friends_only)
        import copy
        mock_events.return_value = copy.deepcopy(sample_events)
        mock_state.return_value = {"status": "friends", "request_id": None}
        mock_friends.return_value = sample_friends_page

        from app.services.public_profile_service import build_public_profile
        result = build_public_profile(TARGET_USER_ID, FRIEND_USER_ID)

        # Friend sees bio, interests, friends, upcoming, and past events
        assert result["username"] == "alex"
        assert result["full_name"] == "Alex Smith"
        assert result["bio"] == "Adventurer and coder"
        assert result["interests"] == ["hiking", "gaming"]
        assert len(result["friends"]) == 1
        assert len(result["events"]["organized"]["upcoming"]) == 1
        assert len(result["events"]["organized"]["past"]) == 1

    @patch("app.services.public_profile_service.get_public_profile")
    @patch("app.services.public_profile_service.get_profile_events")
    @patch("app.services.public_profile_service.get_friendship_state")
    @patch("app.services.public_profile_service.get_user_friends_summary_page")
    def test_friends_only_profile_seen_by_non_friend(
        self, mock_friends, mock_state, mock_events, mock_profile,
        target_profile_friends_only, sample_events, sample_friends_page
    ):
        mock_profile.return_value = dict(target_profile_friends_only)
        mock_state.return_value = {"status": "none", "request_id": None}

        from app.services.public_profile_service import build_public_profile
        result = build_public_profile(TARGET_USER_ID, NON_FRIEND_USER_ID)

        # Non-friend sees ONLY username, full_name, profile picture (avatar_url, avatar_kind, icon_id), and banner
        assert result["username"] == "alex"
        assert result["full_name"] == "Alex Smith"
        assert result["avatar_url"] == "https://example.com/avatar.jpg"
        assert result["avatar_kind"] == "photo"
        assert result["banner_url"] == "https://example.com/banner.jpg"
        assert result["id"] == TARGET_USER_ID
        assert result["friendship"] == {"status": "none", "request_id": None}

        # Bio, interests, events, and friends MUST NOT be in the result
        assert "bio" not in result
        assert "interests" not in result
        assert "events" not in result
        assert "friends" not in result
        mock_events.assert_not_called()
        mock_friends.assert_not_called()


class TestAnotherUserFriendsEndpoint:
    """Test GET /api/profile/{user_id}/friends."""

    @patch("app.api.v1.profile_routes.get_public_profile")
    @patch("app.api.v1.profile_routes.get_friendship_state")
    @patch("app.api.v1.profile_routes.get_user_friends_summary_page")
    def test_non_friend_requests_friends_only_friends_list_refused(
        self, mock_friends_page, mock_state, mock_profile, target_profile_friends_only
    ):
        app.dependency_overrides[get_current_user] = lambda: MockUser(NON_FRIEND_USER_ID)
        try:
            mock_profile.return_value = dict(target_profile_friends_only)
            mock_state.return_value = {"status": "none", "request_id": None}

            resp = client.get(
                f"/api/profile/{TARGET_USER_ID}/friends",
                headers={"Authorization": "Bearer token"},
            )
            assert resp.status_code == 403
            assert resp.json()["detail"] == "This user's friends list is only visible to friends."
            mock_friends_page.assert_not_called()
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    @patch("app.api.v1.profile_routes.get_public_profile")
    @patch("app.api.v1.profile_routes.get_friendship_state")
    @patch("app.api.v1.profile_routes.get_user_friends_summary_page")
    def test_friend_requests_friends_only_friends_list_allowed(
        self, mock_friends_page, mock_state, mock_profile, target_profile_friends_only, sample_friends_page
    ):
        app.dependency_overrides[get_current_user] = lambda: MockUser(FRIEND_USER_ID)
        try:
            mock_profile.return_value = dict(target_profile_friends_only)
            mock_state.return_value = {"status": "friends", "request_id": None}
            mock_friends_page.return_value = sample_friends_page

            resp = client.get(
                f"/api/profile/{TARGET_USER_ID}/friends?page=1&limit=10",
                headers={"Authorization": "Bearer token"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["page"] == 1
            assert data["limit"] == 10
            assert len(data["data"]) == 1
            assert data["data"][0]["username"] == "sam"
            mock_friends_page.assert_called_once_with(TARGET_USER_ID, page=1, limit=10, viewer_id=FRIEND_USER_ID)
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    @patch("app.api.v1.profile_routes.get_public_profile")
    @patch("app.api.v1.profile_routes.get_friendship_state")
    @patch("app.api.v1.profile_routes.get_user_friends_summary_page")
    def test_non_friend_requests_public_friends_list_allowed(
        self, mock_friends_page, mock_state, mock_profile, target_profile_public, sample_friends_page
    ):
        app.dependency_overrides[get_current_user] = lambda: MockUser(NON_FRIEND_USER_ID)
        try:
            mock_profile.return_value = dict(target_profile_public)
            mock_state.return_value = {"status": "none", "request_id": None}
            mock_friends_page.return_value = sample_friends_page

            resp = client.get(
                f"/api/profile/{TARGET_USER_ID}/friends",
                headers={"Authorization": "Bearer token"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["data"]) == 1
            assert data["data"][0]["username"] == "sam"
        finally:
            app.dependency_overrides.pop(get_current_user, None)


class TestFriendsOnlyOrganizerOnEvent:
    """Test that an organizer with a friends-only profile is still shown on their events."""

    @patch("app.api.v1.event_routes.get_event")
    @patch("app.services.profile_service.supabase")
    def test_friends_only_organizer_shown_on_event(self, mock_sb, mock_get_event):
        event_id = "55555555-5555-5555-5555-555555555555"
        organizer_id = TARGET_USER_ID

        mock_get_event.return_value = {
            "id": event_id,
            "title": "Tech Talk",
            "created_by": organizer_id,
            "status": "active",
        }

        # Mock the profile lookup in get_user_summaries
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.in_.return_value = chain
        chain.execute.return_value = MagicMock(
            data=[
                {
                    "id": organizer_id,
                    "username": "alex",
                    "full_name": "Alex Smith",
                    "avatar_url": "https://example.com/avatar.jpg",
                    "avatar_kind": "photo",
                    "icon_id": None,
                }
            ]
        )

        resp = client.get(f"/api/events/{event_id}")
        assert resp.status_code == 200
        event_data = resp.json()
        assert event_data["organizer"] is not None
        assert event_data["organizer"]["id"] == organizer_id
        assert event_data["organizer"]["username"] == "alex"
        assert event_data["organizer"]["full_name"] == "Alex Smith"
