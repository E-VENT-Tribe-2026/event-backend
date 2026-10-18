"""Participant list privacy and friends attending (Authorization Hardening 12.3, Friends Attending 3.4)."""
import base64
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.dependencies import get_current_user
from tests._supabase_mock import make_table_router

ORGANIZER = "33333333-3333-4333-8333-333333333333"
PARTICIPANT = "11111111-1111-4111-8111-111111111111"
FRIEND = "22222222-2222-4222-8222-222222222222"
STRANGER = "44444444-4444-4444-8444-444444444444"
ADMIN = "55555555-5555-4555-8555-555555555555"
EVENT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SVC = "app.services.participant_service"
EVENT = {"id": EVENT_ID, "title": "Picnic", "created_by": ORGANIZER}


def _row(uid, name):
    return {"user_id": uid, "status": "going",
            "profiles": {"username": name, "full_name": name.title(), "avatar_url": None,
                         "avatar_kind": "icon", "icon_id": "icon_fox"}}


def _jwt(aal="aal1"):
    seg = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{seg({'alg': 'none'})}.{seg({'aal': aal})}.sig"


def _auth(aal="aal1"):
    return {"Authorization": f"Bearer {_jwt(aal)}"}


def _result(data):
    return MagicMock(data=data)


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def _as(user_id):
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)


def _get_list(client, viewer, rows, role="user", friends=(), aal="aal1"):
    """Request the full participant list as viewer. rows is what event_participants holds for this viewer's queries."""
    mock_sb, chains = make_table_router()
    chains["event_participants"].execute.return_value = _result(rows)
    chains["profiles"].execute.return_value = _result({"role": role})
    _as(viewer)
    with patch(f"{SVC}.supabase", mock_sb), \
         patch(f"{SVC}.get_event", return_value=EVENT), \
         patch(f"{SVC}.get_friend_ids", return_value=list(friends)):
        return client.get(f"/api/participants/{EVENT_ID}/participants", headers=_auth(aal))


class TestParticipantListAccess:
    def test_signed_in_stranger_is_refused_on_direct_request(self, client):
        # Not the organizer, not a participant (no membership row), not an administrator.
        res = _get_list(client, STRANGER, rows=[])
        assert res.status_code == 403

    def test_organizer_gets_list(self, client):
        rows = [_row(ORGANIZER, "olga"), _row(PARTICIPANT, "pat")]
        res = _get_list(client, ORGANIZER, rows)
        assert res.status_code == 200
        assert [r["user_id"] for r in res.json()] == [ORGANIZER, PARTICIPANT]

    def test_participant_gets_list_with_friend_marks(self, client):
        rows = [_row(ORGANIZER, "olga"), _row(PARTICIPANT, "pat"), _row(FRIEND, "fay")]
        res = _get_list(client, PARTICIPANT, rows, friends=[FRIEND])
        assert res.status_code == 200
        marks = {r["user_id"]: r["is_friend"] for r in res.json()}
        assert marks == {ORGANIZER: False, PARTICIPANT: False, FRIEND: True}
        first = res.json()[0]
        # Fields the existing screens rely on are unchanged.
        assert set(first["profiles"]) == {"full_name", "avatar_url"}
        assert first["status"] == "going" and "user" in first

    def test_administrator_gets_list(self, client):
        mock_sb, chains = make_table_router()
        chains["event_participants"].execute.side_effect = [_result([]), _result([_row(ORGANIZER, "olga")])]
        chains["profiles"].execute.return_value = _result({"role": "administrator"})
        _as(ADMIN)
        with patch(f"{SVC}.supabase", mock_sb), \
             patch("app.core.dependencies.supabase", mock_sb), \
             patch(f"{SVC}.get_event", return_value=EVENT), \
             patch(f"{SVC}.get_friend_ids", return_value=[]):
            res = client.get(f"/api/participants/{EVENT_ID}/participants", headers=_auth("aal2"))
        assert res.status_code == 200
        assert [r["user_id"] for r in res.json()] == [ORGANIZER]

    def test_administrator_without_mfa_is_refused(self, client):
        mock_sb, chains = make_table_router()
        chains["event_participants"].execute.return_value = _result([])
        chains["profiles"].execute.return_value = _result({"role": "administrator"})
        _as(ADMIN)
        with patch(f"{SVC}.supabase", mock_sb),              patch("app.core.dependencies.supabase", mock_sb),              patch(f"{SVC}.get_event", return_value=EVENT),              patch(f"{SVC}.get_friend_ids", return_value=[]):
            res = client.get(f"/api/participants/{EVENT_ID}/participants", headers=_auth("aal1"))
        assert res.status_code == 403

    def test_count_stays_open_to_any_signed_in_user(self, client):
        _as(STRANGER)
        with patch("app.api.v1.participant_routes.get_event_participants",
                   return_value=[{"user_id": ORGANIZER}, {"user_id": PARTICIPANT}]):
            res = client.get(f"/api/participants/{EVENT_ID}/participants/count")
        assert res.status_code == 200
        assert res.json() == {"event_id": EVENT_ID, "count": 2}


class TestFriendsAttending:
    def test_non_participant_gets_only_friends(self, client):
        mock_sb, chains = make_table_router()
        chains["event_participants"].execute.return_value = _result([_row(FRIEND, "fay")])
        _as(STRANGER)
        with patch(f"{SVC}.supabase", mock_sb), \
             patch(f"{SVC}.get_event", return_value=EVENT), \
             patch(f"{SVC}.get_friend_ids", return_value=[FRIEND]):
            res = client.get(f"/api/participants/{EVENT_ID}/participants/friends")
        assert res.status_code == 200
        body = res.json()
        assert [r["user_id"] for r in body] == [FRIEND]
        assert body[0]["user"]["username"] == "fay"
        assert body[0]["user"]["full_name"] == "Fay"
        assert "avatar_url" in body[0]["user"]
        assert body[0]["is_friend"] is True

    def test_no_friends_returns_empty_list(self, client):
        mock_sb, _ = make_table_router()
        _as(STRANGER)
        with patch(f"{SVC}.supabase", mock_sb), \
             patch(f"{SVC}.get_event", return_value=EVENT), \
             patch(f"{SVC}.get_friend_ids", return_value=[]):
            res = client.get(f"/api/participants/{EVENT_ID}/participants/friends")
        assert res.status_code == 200 and res.json() == []


class TestFriendsAttendingCount:
    def test_counts_per_event_including_organizer(self):
        from app.services.participant_service import attach_friends_attending_count
        mock_sb, chains = make_table_router()
        chains["event_participants"].execute.return_value = _result([
            {"event_id": "e1", "user_id": FRIEND},
            {"event_id": "e1", "user_id": PARTICIPANT},
        ])
        events = [{"id": "e1", "created_by": ORGANIZER}, {"id": "e2", "created_by": FRIEND}, {"id": "e3"}]
        with patch(f"{SVC}.supabase", mock_sb), \
             patch(f"{SVC}.get_friend_ids", return_value=[FRIEND, PARTICIPANT, ORGANIZER]):
            attach_friends_attending_count(events, STRANGER)
        assert [e["friends_attending_count"] for e in events] == [3, 1, 0]

    def test_failure_gives_zero_not_error(self):
        from app.services.participant_service import attach_friends_attending_count
        events = [{"id": "e1"}]
        with patch(f"{SVC}.get_friend_ids", side_effect=RuntimeError("db down")):
            attach_friends_attending_count(events, STRANGER)
        assert events[0]["friends_attending_count"] == 0

    def test_anonymous_viewer_leaves_events_untouched(self):
        from app.services.participant_service import attach_friends_attending_count
        events = [{"id": "e1"}]
        attach_friends_attending_count(events, None)
        assert "friends_attending_count" not in events[0]


class TestIsAdministrator:
    DEP = "app.core.dependencies"

    def _check(self, role, token, fail=False):
        from app.services.participant_service import is_administrator
        mock_sb, chains = make_table_router()
        if fail:
            chains["profiles"].execute.side_effect = RuntimeError("db down")
        else:
            chains["profiles"].execute.return_value = _result({"role": role})
        creds = SimpleNamespace(credentials=token)
        with patch(f"{self.DEP}.supabase", mock_sb):
            return is_administrator(SimpleNamespace(id=ADMIN), creds)

    def test_administrator_with_mfa_token(self):
        assert self._check("administrator", _jwt("aal2")) is True

    @pytest.mark.parametrize("role", ["user", "Administrator", "admin", None])
    def test_other_roles_are_not_administrators(self, role):
        assert self._check(role, _jwt("aal2")) is False

    @pytest.mark.parametrize("token", ["", "garbage", _jwt("aal1")])
    def test_administrator_needs_an_mfa_token(self, token):
        assert self._check("administrator", token) is False

    def test_lookup_failure_is_not_administrator(self):
        assert self._check(None, _jwt("aal2"), fail=True) is False
