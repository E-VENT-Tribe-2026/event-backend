import logging
import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException


class TestGetProfile:
    @patch("app.services.profile_service.supabase")
    def test_returns_profile(self, mock_sb):
        profile = {"id": "u1", "full_name": "Alice"}
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.single.return_value = chain
        chain.execute.return_value = MagicMock(data=profile)

        from app.services.profile_service import get_profile
        result = get_profile("u1")

        assert result == profile

    @patch("app.services.profile_service.supabase")
    def test_raises_404_when_not_found(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.single.return_value = chain
        chain.execute.return_value = MagicMock(data=None)

        from app.services.profile_service import get_profile
        with pytest.raises(HTTPException) as exc:
            get_profile("ghost")
        assert exc.value.status_code == 404


class TestUpdateProfile:
    @patch("app.services.profile_service.supabase")
    def test_update_success(self, mock_sb):
        updated = {"id": "u1", "bio": "Hello"}
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.update.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[updated])

        from app.services.profile_service import update_profile
        result = update_profile("u1", {"bio": "Hello"})

        assert result == updated
        # updated_at is injected automatically
        args = chain.update.call_args[0][0]
        assert "updated_at" in args

    @patch("app.services.profile_service.generate_embedding")
    @patch("app.services.profile_service.supabase")
    def test_update_interests_regenerates_embedding(self, mock_sb, mock_generate):
        mock_generate.return_value = [0.1, 0.2, 0.3]

        # first query: fetch existing interests/bio for partial update embedding compute
        select_chain = MagicMock()
        update_chain = MagicMock()

        mock_sb.table.side_effect = [select_chain, update_chain]
        select_chain.select.return_value = select_chain
        select_chain.eq.return_value = select_chain
        select_chain.single.return_value = select_chain
        select_chain.execute.return_value = MagicMock(data={"interests": ["old"], "bio": "Old bio"})

        # second query: actual update call
        update_chain.update.return_value = update_chain
        update_chain.eq.return_value = update_chain
        update_chain.execute.return_value = MagicMock(data=[{"id": "u1"}])

        from app.services.profile_service import update_profile
        update_profile("u1", {"interests": ["sports", "photography"]})

        payload = update_chain.update.call_args[0][0]
        assert payload["interests"] == ["sports", "photography"]
        assert payload["interest_embedding"] == [0.1, 0.2, 0.3]
        mock_generate.assert_called_once()

    @patch("app.services.profile_service.supabase")
    def test_update_failure_raises_400(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.update.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[])

        from app.services.profile_service import update_profile
        with pytest.raises(HTTPException) as exc:
            update_profile("u1", {"bio": "X"})
        assert exc.value.status_code == 400


class TestUpdateLocation:
    @patch("app.services.profile_service.supabase")
    def test_update_location_success(self, mock_sb):
        updated = {"id": "u1", "latitude": 52.5, "longitude": 13.4}
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.update.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[updated])

        from app.services.profile_service import update_location
        result = update_location("u1", 52.5, 13.4)

        assert result == updated
        args = chain.update.call_args[0][0]
        assert args["latitude"] == 52.5
        assert args["longitude"] == 13.4

    @patch("app.services.profile_service.supabase")
    def test_update_location_failure_raises_400(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.update.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[])

        from app.services.profile_service import update_location
        with pytest.raises(HTTPException) as exc:
            update_location("u1", 52.5, 13.4)
        assert exc.value.status_code == 400


class TestGetPublicProfile:
    @patch("app.services.profile_service.supabase")
    def test_returns_public_profile(self, mock_sb):
        profile = {"id": "u1", "full_name": "Alice", "visibility": "public"}
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.single.return_value = chain
        chain.execute.return_value = MagicMock(data=profile)

        from app.services.profile_service import get_public_profile
        result = get_public_profile("u1")

        assert result == profile

    @patch("app.services.profile_service.supabase")
    def test_raises_403_for_private_profile(self, mock_sb):
        profile = {"id": "u1", "full_name": "Bob", "visibility": "private"}
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.single.return_value = chain
        chain.execute.return_value = MagicMock(data=profile)

        from app.services.profile_service import get_public_profile
        with pytest.raises(HTTPException) as exc:
            get_public_profile("u1")
        assert exc.value.status_code == 403

    @patch("app.services.profile_service.supabase")
    def test_raises_404_when_not_found(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.single.return_value = chain
        chain.execute.return_value = MagicMock(data=None)

        from app.services.profile_service import get_public_profile
        with pytest.raises(HTTPException) as exc:
            get_public_profile("ghost")
        assert exc.value.status_code == 404


class TestSearchProfiles:
    @patch("app.services.profile_service.supabase")
    def test_returns_matching_profiles(self, mock_sb):
        rows = [{"id": "u1", "full_name": "Alice"}]
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.ilike.return_value = chain
        chain.range.return_value = chain
        chain.execute.return_value = MagicMock(data=rows)

        from app.services.profile_service import search_profiles
        result = search_profiles("alice", page=1, limit=5)

        assert result["data"] == rows
        assert result["page"] == 1
        chain.ilike.assert_called_once_with("username", "%alice%")
        chain.select.assert_called_once_with("id, full_name, avatar_url, bio, visibility")
        chain.range.assert_called_once_with(0, 4)

    @patch("app.services.profile_service.supabase")
    def test_searches_only_public_profiles(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.ilike.return_value = chain
        chain.range.return_value = chain
        chain.execute.return_value = MagicMock(data=[])

        from app.services.profile_service import search_profiles
        search_profiles("Bob")

        chain.eq.assert_any_call("visibility", "public")

    @patch("app.services.profile_service.supabase")
    def test_search_passes_mixed_case_query_unchanged(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.ilike.return_value = chain
        chain.range.return_value = chain
        chain.execute.return_value = MagicMock(data=[])

        from app.services.profile_service import search_profiles
        search_profiles("JoHn_4")

        chain.ilike.assert_called_once_with("username", "%JoHn_4%")


class TestGetUsername:
    @patch("app.services.profile_service.supabase")
    def test_returns_username(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.single.return_value = chain
        chain.execute.return_value = MagicMock(data={"username": "john_42"})

        from app.services.profile_service import get_username
        result = get_username("u1")

        assert result == "john_42"
        mock_sb.table.assert_called_with("profiles")
        chain.select.assert_called_once_with("username, full_name")
        chain.eq.assert_called_once_with("id", "u1")

    @patch("app.services.profile_service.supabase")
    def test_falls_back_to_someone_when_username_empty(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.single.return_value = chain
        chain.execute.return_value = MagicMock(data={"username": None})

        from app.services.profile_service import get_username
        assert get_username("u1") == "Someone"

    @patch("app.services.profile_service.supabase")
    def test_falls_back_to_full_name_when_username_empty(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.single.return_value = chain
        chain.execute.return_value = MagicMock(data={"username": None, "full_name": "Alice Smith"})

        from app.services.profile_service import get_username
        assert get_username("u1") == "Alice Smith"

    @patch("app.services.profile_service.supabase")
    def test_falls_back_to_someone_when_username_and_full_name_blank(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.single.return_value = chain
        chain.execute.return_value = MagicMock(data={"username": "  ", "full_name": "  "})

        from app.services.profile_service import get_username
        assert get_username("u1") == "Someone"

    @patch("app.services.profile_service.supabase")
    def test_falls_back_to_someone_when_lookup_fails(self, mock_sb):
        mock_sb.table.side_effect = Exception("connection error")

        from app.services.profile_service import get_username
        assert get_username("u1") == "Someone"

    @patch("app.services.profile_service.supabase")
    def test_logs_warning_when_lookup_fails(self, mock_sb, caplog):
        mock_sb.table.side_effect = Exception("connection error")

        from app.services.profile_service import get_username
        with caplog.at_level(logging.WARNING, logger="app.services.profile_service"):
            result = get_username("u1")

        assert result == "Someone"
        assert any(
            record.levelname == "WARNING" and "u1" in record.getMessage()
            for record in caplog.records
        )


class TestChooseUsername:
    @patch("app.services.profile_service.supabase")
    def test_choose_username_success(self, mock_sb):
        profile = {"id": "u1", "username": None, "full_name": None}
        updated = {"id": "u1", "username": "john", "full_name": "John Doe"}

        # 1: get profile, 2: check availability, 3: update
        profile_chain = MagicMock()
        profile_chain.select.return_value = profile_chain
        profile_chain.eq.return_value = profile_chain
        profile_chain.single.return_value = profile_chain
        profile_chain.execute.return_value = MagicMock(data=profile)

        avail_chain = MagicMock()
        avail_chain.select.return_value = avail_chain
        avail_chain.eq.return_value = avail_chain
        avail_chain.neq.return_value = avail_chain
        avail_chain.execute.return_value = MagicMock(data=[])

        update_chain = MagicMock()
        update_chain.update.return_value = update_chain
        update_chain.eq.return_value = update_chain
        update_chain.execute.return_value = MagicMock(data=[updated])

        mock_sb.table.side_effect = [profile_chain, avail_chain, update_chain]

        from app.services.profile_service import choose_username
        result = choose_username("u1", "John", "John Doe")

        assert result == updated
        update_args = update_chain.update.call_args[0][0]
        assert update_args["username"] == "john"
        assert update_args["full_name"] == "John Doe"

    @patch("app.services.profile_service.supabase")
    def test_choose_username_already_chosen_raises_400(self, mock_sb):
        profile = {"id": "u1", "username": "existing_user", "full_name": "Existing"}

        profile_chain = MagicMock()
        profile_chain.select.return_value = profile_chain
        profile_chain.eq.return_value = profile_chain
        profile_chain.single.return_value = profile_chain
        profile_chain.execute.return_value = MagicMock(data=profile)

        mock_sb.table.return_value = profile_chain

        from app.services.profile_service import choose_username
        with pytest.raises(HTTPException) as exc:
            choose_username("u1", "new_name", "New Name")

        assert exc.value.status_code == 400
        assert "already been chosen" in exc.value.detail.lower()

    @patch("app.services.profile_service.supabase")
    def test_choose_username_taken_raises_409(self, mock_sb):
        profile = {"id": "u1", "username": None, "full_name": "John"}

        profile_chain = MagicMock()
        profile_chain.select.return_value = profile_chain
        profile_chain.eq.return_value = profile_chain
        profile_chain.single.return_value = profile_chain
        profile_chain.execute.return_value = MagicMock(data=profile)

        avail_chain = MagicMock()
        avail_chain.select.return_value = avail_chain
        avail_chain.eq.return_value = avail_chain
        avail_chain.neq.return_value = avail_chain
        avail_chain.execute.return_value = MagicMock(data=[{"id": "other"}])

        mock_sb.table.side_effect = [profile_chain, avail_chain]

        from app.services.profile_service import choose_username
        with pytest.raises(HTTPException) as exc:
            choose_username("u1", "taken_user", "John Doe")

        assert exc.value.status_code == 409
        assert "username is unavailable" in exc.value.detail.lower()

    @patch("app.services.profile_service.supabase")
    def test_choose_username_profile_not_found_raises_404(self, mock_sb):
        profile_chain = MagicMock()
        profile_chain.select.return_value = profile_chain
        profile_chain.eq.return_value = profile_chain
        profile_chain.single.return_value = profile_chain
        profile_chain.execute.return_value = MagicMock(data=None)

        mock_sb.table.return_value = profile_chain

        from app.services.profile_service import choose_username
        with pytest.raises(HTTPException) as exc:
            choose_username("ghost", "john_42", "John Doe")

        assert exc.value.status_code == 404

    def test_choose_username_invalid_username_raises_400(self):
        from app.services.profile_service import choose_username
        with pytest.raises(HTTPException) as exc:
            choose_username("u1", "a", "John Doe")
        assert exc.value.status_code == 400

    def test_choose_username_invalid_full_name_raises_400(self):
        from app.services.profile_service import choose_username
        with pytest.raises(HTTPException) as exc:
            choose_username("u1", "john_42", "   ")
        assert exc.value.status_code == 400


class TestUpdateProfileUsernameAndFullName:
    @patch("app.services.profile_service.supabase")
    def test_update_profile_leaves_username_as_it_was(self, mock_sb):
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.update.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[{"id": "u1", "username": "alice", "full_name": "Alice Cooper"}])

        from app.services.profile_service import update_profile
        result = update_profile("u1", {"username": "bob", "full_name": "Alice Cooper"})

        # Username must not be changed in the database update payload
        payload = chain.update.call_args[0][0]
        assert "username" not in payload
        assert payload["full_name"] == "Alice Cooper"
        assert result["username"] == "alice"

    @patch("app.services.profile_service.supabase")
    def test_update_profile_blank_full_name_raises_400(self, mock_sb):
        from app.services.profile_service import update_profile
        with pytest.raises(HTTPException) as exc:
            update_profile("u1", {"full_name": "  "})

        assert exc.value.status_code == 400
        assert "full name is required" in exc.value.detail.lower()

    @patch("app.services.profile_service.supabase")
    def test_update_profile_empty_full_name_raises_400(self, mock_sb):
        from app.services.profile_service import update_profile
        with pytest.raises(HTTPException) as exc:
            update_profile("u1", {"full_name": ""})

        assert exc.value.status_code == 400
        assert "full name is required" in exc.value.detail.lower()

    @patch("app.services.profile_service.supabase")
    def test_update_profile_invalid_short_full_name_raises_400(self, mock_sb):
        from app.services.profile_service import update_profile
        with pytest.raises(HTTPException) as exc:
            update_profile("u1", {"full_name": "Jo"})

        assert exc.value.status_code == 400
        assert "between 3 and 50" in exc.value.detail.lower()

    @patch("app.services.profile_service.supabase")
    def test_update_profile_full_name_without_letters_raises_400(self, mock_sb):
        from app.services.profile_service import update_profile
        with pytest.raises(HTTPException) as exc:
            update_profile("u1", {"full_name": "12345"})

        assert exc.value.status_code == 400
        assert "at least one letter" in exc.value.detail.lower()


class TestTicket121ProfileFields:
    @patch("app.services.profile_service.supabase")
    def test_get_profile_returns_banner_and_default_avatar_kind(self, mock_sb):
        profile_data = {
            "id": "u1",
            "username": "alice",
            "full_name": "Alice Smith",
            "banner_url": "banner_sunset",
            "avatar_url": "https://example.com/photo.jpg",
            "avatar_kind": None,
            "icon_id": None
        }
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.single.return_value = chain
        chain.execute.return_value = MagicMock(data=profile_data)

        from app.services.profile_service import get_profile
        result = get_profile("u1")

        assert result["username"] == "alice"
        assert result["full_name"] == "Alice Smith"
        assert result["banner"] == "banner_sunset"
        assert result["banner_url"] == "banner_sunset"
        assert result["avatar_kind"] == "icon"

    @patch("app.services.profile_service.supabase")
    def test_get_profile_returns_photo_avatar_kind(self, mock_sb):
        profile_data = {
            "id": "u1",
            "username": "bob",
            "full_name": "Bob Jones",
            "banner_url": None,
            "avatar_url": "https://example.com/avatar.jpg",
            "avatar_kind": "photo",
            "icon_id": None
        }
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.single.return_value = chain
        chain.execute.return_value = MagicMock(data=profile_data)

        from app.services.profile_service import get_profile
        result = get_profile("u1")

        assert result["banner"] is None
        assert result["avatar_kind"] == "photo"

    @patch("app.services.profile_service.supabase")
    def test_update_profile_accepts_banner_and_avatar_kind_photo(self, mock_sb):
        updated_row = {
            "id": "u1",
            "username": "alice",
            "full_name": "Alice",
            "banner_url": "banner_mountains",
            "avatar_kind": "photo",
            "avatar_url": "https://example.com/my_upload.png"
        }
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.update.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[updated_row])

        from app.services.profile_service import update_profile
        result = update_profile("u1", {
            "banner": "banner_mountains",
            "avatar_kind": "photo",
            "avatar_url": "https://example.com/my_upload.png"
        })

        payload = chain.update.call_args[0][0]
        assert payload["banner_url"] == "banner_mountains"
        assert payload["avatar_kind"] == "photo"
        assert payload["avatar_url"] == "https://example.com/my_upload.png"
        assert result["banner"] == "banner_mountains"
        assert result["avatar_kind"] == "photo"

    @patch("app.services.profile_service.supabase")
    def test_update_profile_accepts_icon_avatar_kind_and_icon_id(self, mock_sb):
        updated_row = {
            "id": "u1",
            "username": "alice",
            "banner_url": None,
            "avatar_kind": "icon",
            "icon_id": "icon_robot"
        }
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.update.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[updated_row])

        from app.services.profile_service import update_profile
        result = update_profile("u1", {
            "avatar_kind": "icon",
            "icon_id": "icon_robot"
        })

        payload = chain.update.call_args[0][0]
        assert payload["avatar_kind"] == "icon"
        assert payload["icon_id"] == "icon_robot"
        assert result["avatar_kind"] == "icon"

    @patch("app.services.profile_service.supabase")
    def test_update_profile_profile_picture_alias(self, mock_sb):
        updated_row = {
            "id": "u1",
            "avatar_kind": "photo"
        }
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.update.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[updated_row])

        from app.services.profile_service import update_profile
        update_profile("u1", {"profile_picture": "photo"})

        payload = chain.update.call_args[0][0]
        assert payload["avatar_kind"] == "photo"

    @patch("app.services.profile_service.supabase")
    def test_update_profile_invalid_avatar_kind_raises_400(self, mock_sb):
        from app.services.profile_service import update_profile
        with pytest.raises(HTTPException) as exc:
            update_profile("u1", {"avatar_kind": "drawing"})

        assert exc.value.status_code == 400
        assert "must be either 'photo' or 'icon'" in exc.value.detail

    @patch("app.services.profile_service.supabase")
    def test_update_profile_stays_valid_without_banner(self, mock_sb):
        updated_row = {
            "id": "u1",
            "full_name": "Alice Updated",
            "banner_url": None
        }
        chain = MagicMock()
        mock_sb.table.return_value = chain
        chain.update.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[updated_row])

        from app.services.profile_service import update_profile
        result = update_profile("u1", {"full_name": "Alice Updated", "banner": None})

        payload = chain.update.call_args[0][0]
        assert payload["banner_url"] is None
        assert result["full_name"] == "Alice Updated"
        assert result["banner"] is None


# ────────────────────────────────────────────────────────────────────────────
# Ticket #122 P1: user identity summaries (build_user_summary / get_user_summaries)
# ────────────────────────────────────────────────────────────────────────────

class TestBuildUserSummary:
    def test_keys_exact(self):
        from app.services.profile_service import build_user_summary
        row = {
            "id": "u1",
            "username": "john_42",
            "full_name": "John Doe",
            "avatar_url": None,
            "avatar_kind": "icon",
            "icon_id": "icon_fox",
        }
        result = build_user_summary(row)
        assert set(result.keys()) == {
            "id", "username", "full_name", "display_name",
            "avatar_kind", "icon_id", "avatar_url",
        }

    def test_username_set_becomes_display_name(self):
        from app.services.profile_service import build_user_summary
        row = {
            "id": "u1",
            "username": "  john_42  ",
            "full_name": "John Doe",
            "avatar_url": None,
            "avatar_kind": "icon",
            "icon_id": "icon_fox",
        }
        result = build_user_summary(row)
        assert result["username"] == "john_42"
        assert result["display_name"] == "john_42"
        assert result["avatar_kind"] == "icon"
        assert result["icon_id"] == "icon_fox"

    def test_username_whitespace_only_becomes_none(self):
        from app.services.profile_service import build_user_summary
        row = {
            "id": "u1",
            "username": "   ",
            "full_name": "John Doe",
            "avatar_url": None,
            "avatar_kind": None,
            "icon_id": None,
        }
        result = build_user_summary(row)
        assert result["username"] is None
        assert result["display_name"] == "John Doe"
        assert result["avatar_kind"] == "icon"

    def test_missing_username_falls_back_to_full_name(self):
        from app.services.profile_service import build_user_summary
        row = {
            "id": "u1",
            "username": None,
            "full_name": "Legacy Larry",
            "avatar_url": "https://example.com/p.png",
            "avatar_kind": "photo",
            "icon_id": None,
        }
        result = build_user_summary(row)
        assert result["username"] is None
        assert result["display_name"] == "Legacy Larry"
        assert result["avatar_kind"] == "photo"
        assert result["avatar_url"] == "https://example.com/p.png"

    def test_no_username_no_full_name_display_name_none(self):
        from app.services.profile_service import build_user_summary
        row = {
            "id": "u1",
            "username": None,
            "full_name": None,
            "avatar_url": None,
            "avatar_kind": None,
            "icon_id": None,
        }
        result = build_user_summary(row)
        assert result["display_name"] is None

    def test_avatar_kind_case_insensitive(self):
        from app.services.profile_service import build_user_summary
        row = {
            "id": "u1", "username": "a", "full_name": "A",
            "avatar_url": "https://x/y.png", "avatar_kind": "PHOTO", "icon_id": None,
        }
        result = build_user_summary(row)
        assert result["avatar_kind"] == "photo"

    def test_avatar_kind_unknown_value_defaults_to_icon(self):
        from app.services.profile_service import build_user_summary
        row = {
            "id": "u1", "username": "a", "full_name": "A",
            "avatar_url": None, "avatar_kind": "drawing", "icon_id": None,
        }
        result = build_user_summary(row)
        assert result["avatar_kind"] == "icon"

    def test_missing_id_uses_user_id_param(self):
        from app.services.profile_service import build_user_summary
        row = {
            "username": "a", "full_name": "A",
            "avatar_url": None, "avatar_kind": "icon", "icon_id": "icon_fox",
        }
        result = build_user_summary(row, user_id="fallback-id")
        assert result["id"] == "fallback-id"

    def test_profile_present_id_takes_priority_over_user_id_param(self):
        from app.services.profile_service import build_user_summary
        row = {
            "id": "real-id", "username": "a", "full_name": "A",
            "avatar_url": None, "avatar_kind": "icon", "icon_id": None,
        }
        result = build_user_summary(row, user_id="ignored-id")
        assert result["id"] == "real-id"

    def test_profile_none_returns_stub(self):
        from app.services.profile_service import build_user_summary
        result = build_user_summary(None, user_id="ghost-id")
        assert result == {
            "id": "ghost-id",
            "username": None,
            "full_name": None,
            "display_name": None,
            "avatar_kind": "icon",
            "icon_id": None,
            "avatar_url": None,
        }


class TestGetUserSummaries:
    def test_empty_input_returns_empty_dict_no_call(self):
        with patch("app.services.profile_service.supabase") as mock_sb:
            from app.services.profile_service import get_user_summaries
            result = get_user_summaries([])
            assert result == {}
            mock_sb.table.assert_not_called()

    def test_falsy_and_duplicate_ids_dropped_before_query(self):
        with patch("app.services.profile_service.supabase") as mock_sb:
            chain = MagicMock()
            mock_sb.table.return_value = chain
            chain.select.return_value = chain
            chain.in_.return_value = chain
            chain.execute.return_value = MagicMock(data=[])

            from app.services.profile_service import get_user_summaries
            get_user_summaries(["u1", None, "u1", "", "u2"])

            mock_sb.table.assert_called_once_with("profiles")
            called_ids = chain.in_.call_args[0][1]
            assert set(called_ids) == {"u1", "u2"}

    def test_uses_user_summary_columns_select(self):
        with patch("app.services.profile_service.supabase") as mock_sb:
            from app.services.profile_service import USER_SUMMARY_COLUMNS
            chain = MagicMock()
            mock_sb.table.return_value = chain
            chain.select.return_value = chain
            chain.in_.return_value = chain
            chain.execute.return_value = MagicMock(data=[])

            from app.services.profile_service import get_user_summaries
            get_user_summaries(["u1"])

            chain.select.assert_called_once_with(USER_SUMMARY_COLUMNS)
            for field in ("id", "username", "full_name", "avatar_url", "avatar_kind", "icon_id"):
                assert field in USER_SUMMARY_COLUMNS

    def test_returns_summary_per_row_and_stub_for_missing_ids(self):
        with patch("app.services.profile_service.supabase") as mock_sb:
            chain = MagicMock()
            mock_sb.table.return_value = chain
            chain.select.return_value = chain
            chain.in_.return_value = chain
            chain.execute.return_value = MagicMock(data=[
                {
                    "id": "u1", "username": "john_42", "full_name": "John Doe",
                    "avatar_url": None, "avatar_kind": "icon", "icon_id": "icon_fox",
                },
            ])

            from app.services.profile_service import get_user_summaries, build_user_summary
            result = get_user_summaries(["u1", "u2"])

            assert set(result.keys()) == {"u1", "u2"}
            assert result["u1"]["username"] == "john_42"
            assert result["u1"]["icon_id"] == "icon_fox"
            assert result["u2"] == build_user_summary(None, "u2")

    def test_missing_ids_are_logged_and_still_get_a_stub(self, caplog):
        with patch("app.services.profile_service.supabase") as mock_sb:
            chain = MagicMock()
            mock_sb.table.return_value = chain
            chain.select.return_value = chain
            chain.in_.return_value = chain
            chain.execute.return_value = MagicMock(data=[
                {
                    "id": "u1", "username": "john_42", "full_name": "John Doe",
                    "avatar_url": None, "avatar_kind": "icon", "icon_id": "icon_fox",
                },
            ])

            with caplog.at_level(logging.WARNING, logger="app.services.profile_service"):
                from app.services.profile_service import get_user_summaries, build_user_summary
                result = get_user_summaries(["u1", "u2"])

            warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
            assert any("u2" in r.getMessage() for r in warning_records)
            assert result["u2"] == build_user_summary(None, "u2")

    def test_query_exception_returns_stubs_for_all_requested_ids(self):
        with patch("app.services.profile_service.supabase") as mock_sb:
            mock_sb.table.side_effect = Exception("boom")

            from app.services.profile_service import get_user_summaries, build_user_summary
            result = get_user_summaries(["u1", "u2"])

            assert result["u1"] == build_user_summary(None, "u1")

    def test_query_exception_logs_error_with_exc_info(self, caplog):
        with patch("app.services.profile_service.supabase") as mock_sb:
            mock_sb.table.side_effect = Exception("boom")

            with caplog.at_level(logging.ERROR, logger="app.services.profile_service"):
                from app.services.profile_service import get_user_summaries, build_user_summary
                result = get_user_summaries(["u1", "u2"])

            error_records = [r for r in caplog.records if r.levelname == "ERROR"]
            assert len(error_records) == 1
            assert error_records[0].exc_info is not None
            assert result["u1"] == build_user_summary(None, "u1")
            assert result["u2"] == build_user_summary(None, "u2")

    def test_row_missing_id_is_skipped_and_falls_back_to_stub(self):
        with patch("app.services.profile_service.supabase") as mock_sb:
            chain = MagicMock()
            mock_sb.table.return_value = chain
            chain.select.return_value = chain
            chain.in_.return_value = chain
            chain.execute.return_value = MagicMock(data=[
                {"username": "x", "full_name": "X"},
            ])

            from app.services.profile_service import get_user_summaries, build_user_summary
            result = get_user_summaries(["u1"])

            assert result == {"u1": build_user_summary(None, "u1")}


class TestBuildUserSummaryNonStringUsername:
    def test_non_string_username_is_coerced(self):
        from app.services.profile_service import build_user_summary
        row = {"id": "u1", "username": 123, "full_name": "A"}
        result = build_user_summary(row)
        assert result["username"] == "123"
        assert result["display_name"] == "123"
