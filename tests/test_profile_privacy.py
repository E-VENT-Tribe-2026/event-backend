import pytest
from unittest.mock import MagicMock, patch
from uuid import UUID
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.core.dependencies import get_current_user, get_current_onboarded_user
from app.schemas.profile_schema import ProfileUpdateRequest
from app.services.profile_service import update_profile, search_profiles
from app.services.public_profile_service import build_public_profile
from app.services.friendship_service import get_user_friends
from app.services.event_service import attach_organizers

client = TestClient(app)

TARGET_ID = "11111111-1111-4111-8111-111111111111"
VIEWER_ID = "22222222-2222-4222-8222-222222222222"
FRIEND_ID = "33333333-3333-4333-8333-333333333333"


class MockUser:
    def __init__(self, uid=VIEWER_ID):
        self.id = uid
        self.email = "test@example.com"


# -------------------------------------------------------------------------
# 1. Profile Update Visibility Setting & Refusal
# -------------------------------------------------------------------------
class TestProfileVisibilityUpdate:
    @pytest.mark.parametrize("input_val,expected_val", [
        ("public", "public"),
        ("friends_only", "friends_only"),
        ("friends only", "friends_only"),
        ("PUBLIC", "public"),
        ("FRIENDS_ONLY", "friends_only"),
        ("Friends Only", "friends_only"),
    ])
    def test_schema_accepts_allowed_visibility_values(self, input_val, expected_val):
        req = ProfileUpdateRequest(visibility=input_val)
        assert req.visibility == expected_val

    @pytest.mark.parametrize("bad_val", [
        "private",
        "hidden",
        "followers",
        "custom",
        "invalid",
        "123",
    ])
    def test_schema_rejects_disallowed_visibility(self, bad_val):
        with pytest.raises(ValueError) as exc:
            ProfileUpdateRequest(visibility=bad_val)
        assert "Visibility must be either 'public' or 'friends only'." in str(exc.value)

    @patch("app.services.profile_service.supabase")
    def test_service_update_profile_accepts_and_saves_friends_only(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        for m in ("update", "eq"):
            getattr(chain, m).return_value = chain
        chain.execute.return_value = MagicMock(data=[{
            "id": VIEWER_ID,
            "visibility": "friends_only",
            "full_name": "Test User",
        }])

        result = update_profile(VIEWER_ID, {"visibility": "friends only"})
        assert result["visibility"] == "friends_only"
        chain.update.assert_called_once()
        update_args = chain.update.call_args[0][0]
        assert update_args["visibility"] == "friends_only"

    @patch("app.services.profile_service.supabase")
    def test_service_update_profile_refuses_invalid_visibility(self, mock_sb):
        with pytest.raises(HTTPException) as exc:
            update_profile(VIEWER_ID, {"visibility": "private"})
        assert exc.value.status_code == 400
        assert exc.value.detail == "Visibility must be either 'public' or 'friends only'."


# -------------------------------------------------------------------------
# 2. Search Profiles Includes Friends-Only
# -------------------------------------------------------------------------
class TestSearchProfilesVisibility:
    @patch("app.services.profile_service.supabase")
    def test_search_queries_both_public_and_friends_only(self, mock_sb):
        chain = MagicMock()
        for m in ("select", "in_", "ilike", "neq", "order", "range"):
            getattr(chain, m).return_value = chain
        mock_sb.table.return_value = chain
        chain.execute.return_value = MagicMock(data=[
            {"id": "u1", "username": "alice", "visibility": "public"},
            {"id": "u2", "username": "alice_private", "visibility": "friends_only"},
        ])

        res = search_profiles("alice", 1, 10, VIEWER_ID)
        chain.in_.assert_called_once_with("visibility", ["public", "friends_only", "friends only"])
        chain.neq.assert_called_once_with("id", VIEWER_ID)
        assert len(res["data"]) == 2


# -------------------------------------------------------------------------
# 3. Profile Viewing Rules (Friend vs Non-Friend, Public vs Friends-Only)
# -------------------------------------------------------------------------
class TestProfileViewingPrivacy:
    @pytest.fixture
    def mock_events(self):
        return {
            "organized": {
                "upcoming": [{"id": "e1", "title": "Upcoming Hike", "status": "active"}],
                "past": [{"id": "e2", "title": "Past Picnic", "status": "active"}],
            },
            "joined": {
                "upcoming": [{"id": "e3", "title": "Upcoming Concert", "status": "active"}],
                "past": [{"id": "e4", "title": "Past Gala", "status": "active"}],
            },
        }

    @pytest.fixture
    def mock_profile(self):
        return {
            "id": TARGET_ID,
            "username": "target_user",
            "full_name": "Target Person",
            "avatar_url": "https://example.com/avatar.jpg",
            "avatar_kind": "photo",
            "icon_id": None,
            "banner_url": "banner_mountain",
            "banner": "banner_mountain",
            "bio": "I love outdoor adventures and technology.",
            "interests": ["hiking", "coding"],
            "visibility": "public",
        }

    @patch("app.services.public_profile_service.get_profile_friends")
    @patch("app.services.public_profile_service.get_friendship_state")
    @patch("app.services.public_profile_service.get_profile_events")
    @patch("app.services.public_profile_service.get_public_profile")
    def test_public_profile_seen_by_friend_gets_all_events_and_friends(
        self, mock_get_profile, mock_get_events, mock_get_fstate, mock_get_friends, mock_profile, mock_events
    ):
        mock_get_profile.return_value = dict(mock_profile, visibility="public")
        mock_get_events.return_value = mock_events
        mock_get_fstate.return_value = {"status": "friends", "request_id": None}
        mock_get_friends.return_value = [{"id": FRIEND_ID, "username": "friend1", "full_name": "Friend One"}]

        result = build_public_profile(TARGET_ID, VIEWER_ID)

        assert result["username"] == "target_user"
        assert result["full_name"] == "Target Person"
        assert result["bio"] == "I love outdoor adventures and technology."
        assert result["interests"] == ["hiking", "coding"]
        assert len(result["friends"]) == 1
        assert len(result["events"]["organized"]["upcoming"]) == 1
        assert len(result["events"]["organized"]["past"]) == 1
        assert len(result["events"]["joined"]["upcoming"]) == 1
        assert len(result["events"]["joined"]["past"]) == 1

    @patch("app.services.public_profile_service.get_profile_friends")
    @patch("app.services.public_profile_service.get_friendship_state")
    @patch("app.services.public_profile_service.get_profile_events")
    @patch("app.services.public_profile_service.get_public_profile")
    def test_public_profile_seen_by_non_friend_has_no_upcoming_events(
        self, mock_get_profile, mock_get_events, mock_get_fstate, mock_get_friends, mock_profile, mock_events
    ):
        mock_get_profile.return_value = dict(mock_profile, visibility="public")
        mock_get_events.return_value = mock_events
        mock_get_fstate.return_value = {"status": "none", "request_id": None}
        mock_get_friends.return_value = [{"id": FRIEND_ID, "username": "friend1", "full_name": "Friend One"}]

        result = build_public_profile(TARGET_ID, VIEWER_ID)

        assert result["username"] == "target_user"
        assert result["full_name"] == "Target Person"
        assert result["bio"] == "I love outdoor adventures and technology."
        assert result["interests"] == ["hiking", "coding"]
        assert len(result["friends"]) == 1
        # Upcoming events MUST be empty for non-friends
        assert result["events"]["organized"]["upcoming"] == []
        assert result["events"]["joined"]["upcoming"] == []
        # Past events are preserved
        assert len(result["events"]["organized"]["past"]) == 1
        assert len(result["events"]["joined"]["past"]) == 1

    @patch("app.services.public_profile_service.get_profile_friends")
    @patch("app.services.public_profile_service.get_friendship_state")
    @patch("app.services.public_profile_service.get_profile_events")
    @patch("app.services.public_profile_service.get_public_profile")
    def test_friends_only_profile_seen_by_friend_gets_everything(
        self, mock_get_profile, mock_get_events, mock_get_fstate, mock_get_friends, mock_profile, mock_events
    ):
        mock_get_profile.return_value = dict(mock_profile, visibility="friends_only")
        mock_get_events.return_value = mock_events
        mock_get_fstate.return_value = {"status": "friends", "request_id": None}
        mock_get_friends.return_value = [{"id": FRIEND_ID, "username": "friend1"}]

        result = build_public_profile(TARGET_ID, VIEWER_ID)

        assert result["bio"] == "I love outdoor adventures and technology."
        assert result["interests"] == ["hiking", "coding"]
        assert len(result["friends"]) == 1
        assert len(result["events"]["organized"]["upcoming"]) == 1
        assert len(result["events"]["organized"]["past"]) == 1

    @patch("app.services.public_profile_service.get_profile_friends")
    @patch("app.services.public_profile_service.get_friendship_state")
    @patch("app.services.public_profile_service.get_profile_events")
    @patch("app.services.public_profile_service.get_public_profile")
    def test_friends_only_profile_seen_by_non_friend_returns_limited_fields_only(
        self, mock_get_profile, mock_get_events, mock_get_fstate, mock_get_friends, mock_profile, mock_events
    ):
        mock_get_profile.return_value = dict(mock_profile, visibility="friends_only")
        mock_get_events.return_value = mock_events
        mock_get_fstate.return_value = {"status": "none", "request_id": None}

        result = build_public_profile(TARGET_ID, VIEWER_ID)

        # Allowed fields: username, full_name, profile picture (avatar_url, avatar_kind, icon_id), banner
        assert result["username"] == "target_user"
        assert result["full_name"] == "Target Person"
        assert result["avatar_url"] == "https://example.com/avatar.jpg"
        assert result["avatar_kind"] == "photo"
        assert result["banner"] == "banner_mountain"
        assert result["banner_url"] == "banner_mountain"
        assert result["visibility"] == "friends_only"

        # Disallowed fields must NOT be returned
        assert "bio" not in result
        assert "interests" not in result
        assert "friends" not in result
        assert "events" not in result
        mock_get_events.assert_not_called()
        mock_get_friends.assert_not_called()


# -------------------------------------------------------------------------
# 4. Friends List of Another User (Endpoint & Service)
# -------------------------------------------------------------------------
class TestOtherUserFriendsList:
    @patch("app.services.friendship_service.supabase")
    @patch("app.services.friendship_service.get_friendship_state")
    def test_non_friend_requesting_friends_only_friends_list_raises_403(self, mock_fstate, mock_sb):
        # Target profile is friends_only
        prof_chain = MagicMock()
        mock_sb.table.return_value = prof_chain
        for m in ("select", "eq", "limit"):
            getattr(prof_chain, m).return_value = prof_chain
        prof_chain.execute.return_value = MagicMock(data=[{"id": TARGET_ID, "visibility": "friends_only"}])

        mock_fstate.return_value = {"status": "none", "request_id": None}

        with pytest.raises(HTTPException) as exc:
            get_user_friends(TARGET_ID, VIEWER_ID)

        assert exc.value.status_code == 403
        assert exc.value.detail == "This user's friends list is visible only to friends."

    @patch("app.services.friendship_service.get_user_summaries")
    @patch("app.services.friendship_service.supabase")
    @patch("app.services.friendship_service.get_friendship_state")
    def test_friend_requesting_friends_only_friends_list_succeeds(self, mock_fstate, mock_sb, mock_summaries):
        prof_chain = MagicMock()
        fs_chain = MagicMock()

        def table_router(table_name):
            if table_name == "profiles":
                return prof_chain
            if table_name == "friendships":
                return fs_chain
            return MagicMock()

        mock_sb.table.side_effect = table_router

        for m in ("select", "eq", "limit"):
            getattr(prof_chain, m).return_value = prof_chain
        prof_chain.execute.return_value = MagicMock(data=[{"id": TARGET_ID, "visibility": "friends_only"}])

        for m in ("select", "or_", "order", "range"):
            getattr(fs_chain, m).return_value = fs_chain
        fs_chain.execute.return_value = MagicMock(data=[
            {"id": 1, "user_id": TARGET_ID, "friend_id": FRIEND_ID, "created_at": "2026-01-01T00:00:00Z"}
        ])

        mock_fstate.return_value = {"status": "friends", "request_id": None}
        mock_summaries.return_value = {
            FRIEND_ID: {
                "id": FRIEND_ID,
                "username": "friend_user",
                "full_name": "Friend User",
                "avatar_kind": "icon",
                "icon_id": "icon_fox",
                "avatar_url": None,
                "display_name": "friend_user",
            }
        }

        result = get_user_friends(TARGET_ID, VIEWER_ID, page=1, limit=10)
        assert result["page"] == 1
        assert result["limit"] == 10
        assert result["has_more"] is False
        assert len(result["data"]) == 1
        assert result["data"][0]["username"] == "friend_user"

    @patch("app.services.friendship_service.get_user_summaries")
    @patch("app.services.friendship_service.supabase")
    @patch("app.services.friendship_service.get_friendship_state")
    def test_non_friend_requesting_public_friends_list_succeeds(self, mock_fstate, mock_sb, mock_summaries):
        prof_chain = MagicMock()
        fs_chain = MagicMock()

        def table_router(table_name):
            if table_name == "profiles":
                return prof_chain
            if table_name == "friendships":
                return fs_chain
            return MagicMock()

        mock_sb.table.side_effect = table_router

        for m in ("select", "eq", "limit"):
            getattr(prof_chain, m).return_value = prof_chain
        prof_chain.execute.return_value = MagicMock(data=[{"id": TARGET_ID, "visibility": "public"}])

        for m in ("select", "or_", "order", "range"):
            getattr(fs_chain, m).return_value = fs_chain
        fs_chain.execute.return_value = MagicMock(data=[
            {"id": 1, "user_id": TARGET_ID, "friend_id": FRIEND_ID, "created_at": "2026-01-01T00:00:00Z"}
        ])

        mock_fstate.return_value = {"status": "none", "request_id": None}
        mock_summaries.return_value = {
            FRIEND_ID: {
                "id": FRIEND_ID,
                "username": "friend_user",
                "full_name": "Friend User",
                "avatar_kind": "icon",
                "icon_id": "icon_fox",
                "avatar_url": None,
                "display_name": "friend_user",
            }
        }

        result = get_user_friends(TARGET_ID, VIEWER_ID, page=1, limit=10)
        assert len(result["data"]) == 1
        assert result["data"][0]["username"] == "friend_user"


# -------------------------------------------------------------------------
# 5. Direct API Route Tests for Non-Friend Accessing Friends-Only
# -------------------------------------------------------------------------
class TestDirectProfileApiRoutes:
    def test_direct_request_friends_only_profile_and_friends_list_as_non_friend(self):
        app.dependency_overrides[get_current_user] = lambda: MockUser(VIEWER_ID)
        try:
            with patch("app.api.v1.profile_routes.build_public_profile") as mock_build, \
                 patch("app.api.v1.profile_routes.get_user_friends") as mock_get_friends:

                # 1. Profile response returns ONLY allowed data
                mock_build.return_value = {
                    "id": TARGET_ID,
                    "username": "target_user",
                    "full_name": "Target Person",
                    "avatar_url": "https://example.com/avatar.jpg",
                    "avatar_kind": "photo",
                    "icon_id": None,
                    "banner": "banner_sunset",
                    "banner_url": "banner_sunset",
                    "visibility": "friends_only",
                    "friendship": {"status": "none", "request_id": None},
                }

                resp_profile = client.get(f"/api/profile/{TARGET_ID}", headers={"Authorization": "Bearer token"})
                assert resp_profile.status_code == 200
                data = resp_profile.json()
                assert data["username"] == "target_user"
                assert data["full_name"] == "Target Person"
                assert data["avatar_url"] == "https://example.com/avatar.jpg"
                assert data["banner"] == "banner_sunset"
                assert "bio" not in data
                assert "interests" not in data
                assert "events" not in data
                assert "friends" not in data

                # 2. Friends list request returns 403 Forbidden
                mock_get_friends.side_effect = HTTPException(
                    status_code=403,
                    detail="This user's friends list is visible only to friends."
                )

                resp_friends = client.get(f"/api/profile/{TARGET_ID}/friends", headers={"Authorization": "Bearer token"})
                assert resp_friends.status_code == 403
                assert resp_friends.json()["detail"] == "This user's friends list is visible only to friends."
        finally:
            app.dependency_overrides.pop(get_current_user, None)


# -------------------------------------------------------------------------
# 6. Event Organizer with Friends-Only Profile is Still Shown
# -------------------------------------------------------------------------
class TestOrganizerWithFriendsOnlyProfile:
    @patch("app.services.event_service.get_user_summaries")
    def test_friends_only_organizer_is_still_attached_to_event(self, mock_summaries):
        mock_summaries.return_value = {
            TARGET_ID: {
                "id": TARGET_ID,
                "username": "organizer_user",
                "full_name": "Organizer Name",
                "avatar_kind": "icon",
                "icon_id": "icon_star",
                "avatar_url": None,
                "display_name": "organizer_user",
            }
        }

        events = [{
            "id": "e100",
            "title": "Community Gathering",
            "created_by": TARGET_ID,
        }]

        result = attach_organizers(events)
        assert len(result) == 1
        assert result[0]["organizer"]["id"] == TARGET_ID
        assert result[0]["organizer"]["username"] == "organizer_user"
