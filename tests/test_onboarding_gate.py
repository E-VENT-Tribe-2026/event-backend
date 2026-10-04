"""
Tests for the get_current_onboarded_user dependency and the onboarding gate.

Covers:
1. No username  → 403 (unit test)
2. No full_name → 403 (unit test)
3. Fully onboarded → passes through (unit test)
4. Onboarding endpoints remain accessible to incomplete accounts (integration tests)
"""

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.core.dependencies import get_current_user, get_current_onboarded_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class MockUser:
    id = "u1"
    email = "test@test.com"


def _make_supabase_mock(username, full_name):
    """Return a mock supabase client whose profiles query returns the given values."""
    chain = MagicMock()
    chain.table.return_value = chain
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.single.return_value = chain
    chain.execute.return_value = MagicMock(data={"username": username, "full_name": full_name})
    return chain


# ---------------------------------------------------------------------------
# Unit tests: dependency logic in isolation
# ---------------------------------------------------------------------------

class TestOnboardingGateDependency:
    def test_no_username_raises_403(self):
        mock_sb = _make_supabase_mock(username=None, full_name="Alice Smith")
        user = MockUser()

        with patch("app.core.dependencies.supabase", mock_sb):
            with pytest.raises(HTTPException) as exc_info:
                get_current_onboarded_user(user=user)

        assert exc_info.value.status_code == 403
        assert "Profile setup required" in exc_info.value.detail

    def test_empty_username_raises_403(self):
        mock_sb = _make_supabase_mock(username="   ", full_name="Alice Smith")
        user = MockUser()

        with patch("app.core.dependencies.supabase", mock_sb):
            with pytest.raises(HTTPException) as exc_info:
                get_current_onboarded_user(user=user)

        assert exc_info.value.status_code == 403
        assert "Profile setup required" in exc_info.value.detail

    def test_no_full_name_raises_403(self):
        mock_sb = _make_supabase_mock(username="alice42", full_name=None)
        user = MockUser()

        with patch("app.core.dependencies.supabase", mock_sb):
            with pytest.raises(HTTPException) as exc_info:
                get_current_onboarded_user(user=user)

        assert exc_info.value.status_code == 403
        assert "Profile setup required" in exc_info.value.detail

    def test_onboarded_user_passes(self):
        mock_sb = _make_supabase_mock(username="alice42", full_name="Alice Smith")
        user = MockUser()

        with patch("app.core.dependencies.supabase", mock_sb):
            result = get_current_onboarded_user(user=user)

        assert result is user


# ---------------------------------------------------------------------------
# Integration tests: onboarding endpoints must remain accessible
# ---------------------------------------------------------------------------

client = TestClient(app)


class TestOnboardingGateRouteLevel:
    def test_onboarding_endpoints_accessible_to_incomplete_account(self):
        """
        An authenticated user with no username must be able to reach every
        onboarding-exempt endpoint without getting a 403 from the gate.
        The endpoint may still return 400 / 404 / 409 due to test DB state — that is fine.
        """
        # Incomplete user (no username)
        app.dependency_overrides[get_current_user] = lambda: MockUser()

        # Patch the supabase call inside get_current_onboarded_user so that if the
        # dependency is accidentally invoked it would return an incomplete profile.
        incomplete_chain = MagicMock()
        incomplete_chain.table.return_value = incomplete_chain
        incomplete_chain.select.return_value = incomplete_chain
        incomplete_chain.eq.return_value = incomplete_chain
        incomplete_chain.single.return_value = incomplete_chain
        incomplete_chain.execute.return_value = MagicMock(
            data={"username": None, "full_name": None}
        )

        try:
            with patch("app.core.dependencies.supabase", incomplete_chain), \
                 patch("app.api.v1.profile_routes.choose_username",
                       return_value={"id": "u1", "username": "alice42", "full_name": "Alice Smith"}), \
                 patch("app.services.profile_service.choose_username",
                       return_value={"id": "u1", "username": "alice42", "full_name": "Alice Smith"}):

                # POST /api/auth/choose-username — exempt
                response = client.post(
                    "/api/auth/choose-username",
                    json={"username": "alice42", "full_name": "Alice Smith"},
                    headers={"Authorization": "Bearer token"},
                )
                assert response.status_code != 403, (
                    f"POST /api/auth/choose-username returned 403: {response.json()}"
                )

                # POST /api/profile/choose-username — exempt
                response = client.post(
                    "/api/profile/choose-username",
                    json={"username": "alice42", "full_name": "Alice Smith"},
                    headers={"Authorization": "Bearer token"},
                )
                assert response.status_code != 403, (
                    f"POST /api/profile/choose-username returned 403: {response.json()}"
                )

                # POST /api/profile/username — exempt
                response = client.post(
                    "/api/profile/username",
                    json={"username": "alice42", "full_name": "Alice Smith"},
                    headers={"Authorization": "Bearer token"},
                )
                assert response.status_code != 403, (
                    f"POST /api/profile/username returned 403: {response.json()}"
                )

                # PUT /api/profile/username — exempt
                response = client.put(
                    "/api/profile/username",
                    json={"username": "alice42", "full_name": "Alice Smith"},
                    headers={"Authorization": "Bearer token"},
                )
                assert response.status_code != 403, (
                    f"PUT /api/profile/username returned 403: {response.json()}"
                )

            # GET /api/auth/me — exempt; patch the local supabase in auth_routes
            with patch("app.api.v1.auth_routes.supabase") as mock_auth_sb:
                auth_chain = MagicMock()
                mock_auth_sb.table.return_value = auth_chain
                auth_chain.select.return_value = auth_chain
                auth_chain.eq.return_value = auth_chain
                auth_chain.single.return_value = auth_chain
                auth_chain.execute.return_value = MagicMock(data={"username": None})

                response = client.get(
                    "/api/auth/me",
                    headers={"Authorization": "Bearer token"},
                )
                assert response.status_code == 200, (
                    f"GET /api/auth/me returned {response.status_code}: {response.json()}"
                )
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    def test_protected_endpoint_blocked_for_incomplete_account(self):
        """
        An authenticated user without a username must receive 403 from a
        protected endpoint (the onboarding gate must fire).
        """
        # Override get_current_user so auth passes, but do NOT override
        # get_current_onboarded_user — it must run the real check.
        app.dependency_overrides[get_current_user] = lambda: MockUser()

        incomplete_chain = MagicMock()
        incomplete_chain.table.return_value = incomplete_chain
        incomplete_chain.select.return_value = incomplete_chain
        incomplete_chain.eq.return_value = incomplete_chain
        incomplete_chain.single.return_value = incomplete_chain
        incomplete_chain.execute.return_value = MagicMock(
            data={"username": None, "full_name": None}
        )

        try:
            with patch("app.core.dependencies.supabase", incomplete_chain):
                response = client.get(
                    "/api/events/my-events",
                    headers={"Authorization": "Bearer token"},
                )

            assert response.status_code == 403
            assert "Profile setup required" in response.json()["detail"]
        finally:
            app.dependency_overrides.pop(get_current_user, None)
