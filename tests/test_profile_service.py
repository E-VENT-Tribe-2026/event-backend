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
        result = search_profiles("Alice", page=1, limit=5)

        assert result["data"] == rows
        assert result["page"] == 1
        chain.ilike.assert_called_once_with("full_name", "%Alice%")
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
    def test_update_profile_cannot_change_existing_username(self, mock_sb):
        curr_chain = MagicMock()
        curr_chain.select.return_value = curr_chain
        curr_chain.eq.return_value = curr_chain
        curr_chain.single.return_value = curr_chain
        curr_chain.execute.return_value = MagicMock(data={"username": "alice"})

        mock_sb.table.return_value = curr_chain

        from app.services.profile_service import update_profile
        with pytest.raises(HTTPException) as exc:
            update_profile("u1", {"username": "bob"})

        assert exc.value.status_code == 400
        assert "cannot be changed" in exc.value.detail.lower()

    @patch("app.services.profile_service.supabase")
    def test_update_profile_blank_full_name_raises_400(self, mock_sb):
        from app.services.profile_service import update_profile
        with pytest.raises(HTTPException) as exc:
            update_profile("u1", {"full_name": "  "})

        assert exc.value.status_code == 400
        assert "full name is required" in exc.value.detail.lower()