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