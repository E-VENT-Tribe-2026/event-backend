"""Fixes from the team review of dev: join limits, participant emails, invite for Google accounts."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services import participant_service, registration_invite_service


def _iso(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) + delta).isoformat()


class TestJoinLimits:
    def _join(self, event, count=0, already=False):
        sb = MagicMock()
        sb.table.return_value = sb
        sb.select.return_value = sb
        sb.eq.return_value = sb
        sb.insert.return_value = sb
        existing = MagicMock(data=[{"user_id": "u1"}] if already else [])
        counted = MagicMock(data=[], count=count)
        inserted = MagicMock(data=[{"user_id": "u1"}])
        counts_rows = isinstance(event.get("max_capacity"), int)
        sb.execute.side_effect = [existing, counted, inserted] if counts_rows else [existing, inserted]
        with patch.object(participant_service, "supabase", sb), \
             patch.object(participant_service, "get_event", return_value=event), \
             patch.object(participant_service, "is_event_hidden", return_value=False):
            return participant_service.join_event("u1", "e1")

    def test_full_event_is_refused(self):
        event = {"id": "e1", "start_datetime": _iso(timedelta(days=1)), "max_capacity": 2}
        with pytest.raises(HTTPException) as err:
            self._join(event, count=2)
        assert err.value.status_code == 400
        assert "maximum capacity" in err.value.detail

    def test_started_event_is_refused(self):
        event = {"id": "e1", "start_datetime": _iso(-timedelta(minutes=1)), "max_capacity": 50}
        with pytest.raises(HTTPException) as err:
            self._join(event)
        assert err.value.status_code == 400
        assert "already started" in err.value.detail

    def test_upcoming_event_with_room_is_joined(self):
        event = {"id": "e1", "start_datetime": _iso(timedelta(days=1)), "max_capacity": 2}
        data, returned = self._join(event, count=1)
        assert data == [{"user_id": "u1"}]
        assert returned is event

    def test_event_without_capacity_has_no_limit(self):
        event = {"id": "e1", "start_datetime": _iso(timedelta(days=1)), "max_capacity": None}
        data, _ = self._join(event, count=500)
        assert data == [{"user_id": "u1"}]


class TestParticipantEmailProvider:
    def _run(self, resend_key, smtp_user, smtp_password):
        from app.services import event_service

        settings = SimpleNamespace(
            RESEND_API_KEY=resend_key, SMTP_USER=smtp_user, SMTP_PASSWORD=smtp_password,
            SUPABASE_URL="https://x.supabase.co", SUPABASE_SERVICE_KEY="k",
        )
        sb = MagicMock()
        sb.table.return_value = sb
        sb.select.return_value = sb
        sb.eq.return_value = sb
        sb.execute.return_value = MagicMock(data=[{"user_id": "p1"}])
        response = MagicMock(status_code=200)
        response.json.return_value = {"email": "p1@example.com"}
        with patch("app.core.config.settings", settings), \
             patch.object(event_service, "supabase", sb), \
             patch("httpx.get", return_value=response), \
             patch("app.services.email_service.send_email") as send:
            event_service._email_participants({"id": "e1", "title": "T"}, "update")
        return send

    def test_resend_alone_sends_the_emails(self):
        assert self._run("re_key", None, None).call_count == 1

    def test_smtp_alone_sends_the_emails(self):
        assert self._run(None, "user", "pass").call_count == 1

    def test_no_provider_sends_nothing(self):
        assert self._run(None, None, None).call_count == 0


class TestInviteToFinishSignup:
    def _user(self, created_at):
        return SimpleNamespace(id="u1", email="new@example.com", created_at=created_at)

    def test_account_older_than_invites_needs_no_code(self):
        user = self._user(datetime(2026, 9, 1, tzinfo=timezone.utc))
        assert registration_invite_service.require_invite_to_finish_signup(user, None) is None

    def test_account_with_redeemed_invite_needs_no_code(self):
        user = self._user(datetime.now(timezone.utc))
        with patch.object(registration_invite_service, "_has_used_invite", return_value=True):
            assert registration_invite_service.require_invite_to_finish_signup(user, None) is None

    def test_new_google_account_without_code_is_refused(self):
        user = self._user(datetime.now(timezone.utc))
        with patch.object(registration_invite_service, "_has_used_invite", return_value=False):
            with pytest.raises(HTTPException) as err:
                registration_invite_service.require_invite_to_finish_signup(user, "")
        assert err.value.status_code == 400
        assert "invitation code is required" in err.value.detail

    def test_new_google_account_with_valid_code_gets_the_invite(self):
        user = self._user(datetime.now(timezone.utc))
        with patch.object(registration_invite_service, "_has_used_invite", return_value=False), \
             patch.object(registration_invite_service, "require_registration_invite",
                          return_value={"id": "inv1"}) as check:
            invite = registration_invite_service.require_invite_to_finish_signup(user, "ABCD-2345")
        assert invite == {"id": "inv1"}
        check.assert_called_once_with("new@example.com", "ABCD-2345")

    def test_choose_username_route_marks_the_invite_used(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.core.dependencies import get_current_user

        app.dependency_overrides[get_current_user] = lambda: self._user(datetime.now(timezone.utc))
        try:
            with patch.object(registration_invite_service, "require_invite_to_finish_signup",
                              return_value={"id": "inv1"}), \
                 patch.object(registration_invite_service, "mark_registration_invite_used") as mark, \
                 patch("app.services.profile_service.choose_username",
                       return_value={"id": "u1", "username": "newbie"}):
                res = TestClient(app).post(
                    "/api/auth/choose-username",
                    json={"username": "newbie", "full_name": "New User", "invite_code": "ABCD-2345"},
                    headers={"Authorization": "Bearer token"},
                )
            assert res.status_code == 200
            mark.assert_called_once_with("inv1", "u1")
        finally:
            app.dependency_overrides.pop(get_current_user, None)
