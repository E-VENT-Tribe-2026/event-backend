"""Tests for event invitations (ticket #186)."""
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from tests._supabase_mock import make_table_router

ME = "11111111-1111-4111-8111-111111111111"
FRIEND = "22222222-2222-4222-8222-222222222222"
ORGANIZER = "33333333-3333-4333-8333-333333333333"
OTHER = "44444444-4444-4444-8444-444444444444"
EVENT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
MOD = "app.services.invitation_service"


def _future(days=3):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _past(days=1):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _event(start=None, status="active", organizer=ORGANIZER):
    return {"id": EVENT_ID, "title": "Beach Volleyball", "start_datetime": start or _future(),
            "status": status, "created_by": organizer}


def _result(data=None, count=None):
    res = MagicMock()
    res.data = data
    res.count = count
    return res


def _summaries(ids):
    return {i: {"id": i, "username": f"user_{i[:4]}"} for i in ids}


class UniqueViolation(Exception):
    code = "23505"


class MissingTable(Exception):
    code = "PGRST205"


@contextmanager
def svc(mock_sb, friends=True):
    with ExitStack() as stack:
        stack.enter_context(patch(f"{MOD}.supabase", mock_sb))
        mocks = {
            "get_user_summaries": stack.enter_context(patch(f"{MOD}.get_user_summaries")),
            "get_username": stack.enter_context(patch(f"{MOD}.get_username", return_value="john_42")),
            "_find_friendship": stack.enter_context(
                patch(f"{MOD}._find_friendship", return_value={"id": 1} if friends else None)),
        }
        mocks["get_user_summaries"].side_effect = _summaries
        yield mocks


def _setup_invite(chains, event=None, inviter_attends=True, invitee_attends=False, blocks=None):
    chains["events"].execute.return_value = _result([event or _event()])
    chains["event_participants"].execute.side_effect = [
        _result([{"user_id": ME}] if inviter_attends else []),
        _result([{"user_id": FRIEND}] if invitee_attends else []),
    ]
    chains["user_blocks"].execute.return_value = _result(blocks or [])
    chains["event_invitations"].execute.return_value = _result(
        [{"id": 9, "event_id": EVENT_ID, "inviter_id": ME, "invitee_id": FRIEND,
          "created_at": "2026-10-12T10:00:00+00:00"}])
    chains["notifications"].execute.return_value = _result([{"id": 1}])


def _assert_error(exc_info, status, code):
    assert exc_info.value.status_code == status
    assert exc_info.value.detail["code"] == code


# ---------- invite_friend ----------

class TestInviteFriend:
    def test_participant_invites_friend_and_friend_is_notified(self):
        from app.services.invitation_service import invite_friend
        mock_sb, chains = make_table_router()
        _setup_invite(chains)
        with svc(mock_sb):
            result = invite_friend(ME, EVENT_ID, FRIEND)

        assert result["invitation_id"] == 9
        assert result["user"]["id"] == FRIEND
        chains["event_invitations"].insert.assert_called_once_with(
            {"event_id": EVENT_ID, "inviter_id": ME, "invitee_id": FRIEND})
        payload = chains["notifications"].insert.call_args[0][0]
        assert payload["user_id"] == FRIEND
        assert payload["event_id"] == EVENT_ID
        assert payload["type"] == "event_invitation"
        assert payload["related_user_id"] == ME
        assert payload["invitation_id"] == 9
        assert "john_42" in payload["message"] and "Beach Volleyball" in payload["message"]

    def test_organizer_can_invite_even_without_participant_row(self):
        from app.services.invitation_service import invite_friend
        mock_sb, chains = make_table_router()
        _setup_invite(chains, event=_event(organizer=ME), inviter_attends=False)
        with svc(mock_sb):
            assert invite_friend(ME, EVENT_ID, FRIEND)["invitation_id"] == 9

    def test_full_event_is_allowed(self):
        from app.services.invitation_service import invite_friend
        mock_sb, chains = make_table_router()
        event = _event()
        event["max_capacity"] = 1
        _setup_invite(chains, event=event)
        with svc(mock_sb):
            assert invite_friend(ME, EVENT_ID, FRIEND)["invitation_id"] == 9

    def test_refuses_self(self):
        from app.services.invitation_service import invite_friend
        mock_sb, _ = make_table_router()
        with svc(mock_sb), pytest.raises(HTTPException) as exc:
            invite_friend(ME, EVENT_ID, ME)
        _assert_error(exc, 400, "cannot_invite_self")

    def test_refuses_missing_event(self):
        from app.services.invitation_service import invite_friend
        mock_sb, chains = make_table_router()
        chains["events"].execute.return_value = _result([])
        with svc(mock_sb), pytest.raises(HTTPException) as exc:
            invite_friend(ME, EVENT_ID, FRIEND)
        _assert_error(exc, 404, "event_not_found")

    @pytest.mark.parametrize("event", [_event(status="cancelled"), _event(start=_past())])
    def test_refuses_cancelled_or_past_event(self, event):
        from app.services.invitation_service import invite_friend
        mock_sb, chains = make_table_router()
        _setup_invite(chains, event=event)
        with svc(mock_sb), pytest.raises(HTTPException) as exc:
            invite_friend(ME, EVENT_ID, FRIEND)
        _assert_error(exc, 400, "event_not_upcoming")
        chains["event_invitations"].insert.assert_not_called()

    def test_refuses_user_who_does_not_attend(self):
        from app.services.invitation_service import invite_friend
        mock_sb, chains = make_table_router()
        _setup_invite(chains, inviter_attends=False)
        with svc(mock_sb), pytest.raises(HTTPException) as exc:
            invite_friend(ME, EVENT_ID, FRIEND)
        _assert_error(exc, 403, "not_event_member")

    def test_refuses_non_friend(self):
        from app.services.invitation_service import invite_friend
        mock_sb, chains = make_table_router()
        _setup_invite(chains)
        with svc(mock_sb, friends=False), pytest.raises(HTTPException) as exc:
            invite_friend(ME, EVENT_ID, FRIEND)
        _assert_error(exc, 403, "not_friends")
        chains["event_invitations"].insert.assert_not_called()

    def test_refuses_friend_who_attends(self):
        from app.services.invitation_service import invite_friend
        mock_sb, chains = make_table_router()
        _setup_invite(chains, invitee_attends=True)
        with svc(mock_sb), pytest.raises(HTTPException) as exc:
            invite_friend(ME, EVENT_ID, FRIEND)
        _assert_error(exc, 409, "already_attending")

    @pytest.mark.parametrize("block", [
        {"blocker_id": ORGANIZER, "blocked_id": FRIEND},
        {"blocker_id": FRIEND, "blocked_id": ORGANIZER},
    ])
    def test_refuses_block_either_way_without_saying_why(self, block):
        from app.services.invitation_service import invite_friend
        mock_sb, chains = make_table_router()
        _setup_invite(chains, blocks=[block])
        with svc(mock_sb), pytest.raises(HTTPException) as exc:
            invite_friend(ME, EVENT_ID, FRIEND)
        _assert_error(exc, 403, "cannot_invite")
        assert "block" not in exc.value.detail["message"].lower()
        chains["event_invitations"].insert.assert_not_called()

    def test_missing_blocks_table_means_nobody_is_blocked(self):
        from app.services.invitation_service import invite_friend
        mock_sb, chains = make_table_router()
        _setup_invite(chains)
        chains["user_blocks"].execute.side_effect = MissingTable("relation does not exist")
        with svc(mock_sb):
            assert invite_friend(ME, EVENT_ID, FRIEND)["invitation_id"] == 9

    def test_refuses_second_invitation_from_same_user(self):
        from app.services.invitation_service import invite_friend
        mock_sb, chains = make_table_router()
        _setup_invite(chains)
        chains["event_invitations"].execute.side_effect = UniqueViolation("duplicate key")
        with svc(mock_sb), pytest.raises(HTTPException) as exc:
            invite_friend(ME, EVENT_ID, FRIEND)
        _assert_error(exc, 409, "already_invited")

    def test_notification_failure_does_not_fail_invitation(self):
        from app.services.invitation_service import invite_friend
        mock_sb, chains = make_table_router()
        _setup_invite(chains)
        chains["notifications"].execute.side_effect = RuntimeError("db down")
        with svc(mock_sb):
            assert invite_friend(ME, EVENT_ID, FRIEND)["invitation_id"] == 9


# ---------- get_invitable_friends ----------

class TestInvitableFriends:
    def _setup(self, chains, profiles):
        chains["events"].execute.return_value = _result([_event()])
        chains["friendships"].execute.return_value = _result(
            [{"user_id": ME, "friend_id": p["id"]} for p in profiles])
        chains["profiles"].execute.return_value = _result(profiles)

    def test_returns_status_for_each_friend(self):
        from app.services.invitation_service import get_invitable_friends
        mock_sb, chains = make_table_router()
        profiles = [{"id": FRIEND, "username": "a"}, {"id": OTHER, "username": "b"},
                    {"id": ORGANIZER, "username": "c"}]
        five = "55555555-5555-4555-8555-555555555555"
        profiles.append({"id": five, "username": "d"})
        self._setup(chains, profiles)
        chains["event_participants"].execute.side_effect = [
            _result([{"user_id": ME}]),          # ME attends, so may invite
            _result([]),                         # nobody else attends (organizer counts anyway)
        ]
        chains["event_invitations"].execute.return_value = _result([{"invitee_id": FRIEND}])
        chains["user_blocks"].execute.return_value = _result([{"blocker_id": ORGANIZER, "blocked_id": OTHER}])

        with svc(mock_sb):
            result = get_invitable_friends(ME, EVENT_ID, None, 1, 20)

        statuses = {item["user"]["id"]: item["invite_status"] for item in result["data"]}
        assert statuses == {FRIEND: "invited", OTHER: "unavailable", ORGANIZER: "attending", five: "can_invite"}
        assert [item["can_invite"] for item in result["data"]] == [False, False, False, True]
        assert result["has_more"] is False

    def test_search_filters_by_username_literally(self):
        from app.services.invitation_service import get_invitable_friends
        mock_sb, chains = make_table_router()
        self._setup(chains, [{"id": FRIEND, "username": "jane"}])
        chains["event_participants"].execute.side_effect = [_result([{"user_id": ME}]), _result([])]
        chains["event_invitations"].execute.return_value = _result([])
        chains["user_blocks"].execute.return_value = _result([])
        with svc(mock_sb):
            get_invitable_friends(ME, EVENT_ID, "ja_", 1, 20)
        chains["profiles"].ilike.assert_called_once_with("username", "%ja\\_%")

    def test_pages(self):
        from app.services.invitation_service import get_invitable_friends
        mock_sb, chains = make_table_router()
        self._setup(chains, [{"id": FRIEND, "username": "a"}, {"id": OTHER, "username": "b"}])
        chains["event_participants"].execute.side_effect = [_result([{"user_id": ME}]), _result([])]
        chains["event_invitations"].execute.return_value = _result([])
        chains["user_blocks"].execute.return_value = _result([])
        with svc(mock_sb):
            result = get_invitable_friends(ME, EVENT_ID, None, 2, 1)
        chains["profiles"].range.assert_called_once_with(1, 2)
        assert result["has_more"] is True and len(result["data"]) == 1

    def test_no_friends(self):
        from app.services.invitation_service import get_invitable_friends
        mock_sb, chains = make_table_router()
        self._setup(chains, [])
        chains["event_participants"].execute.return_value = _result([{"user_id": ME}])
        with svc(mock_sb):
            assert get_invitable_friends(ME, EVENT_ID)["data"] == []

    def test_refused_for_non_member(self):
        from app.services.invitation_service import get_invitable_friends
        mock_sb, chains = make_table_router()
        chains["events"].execute.return_value = _result([_event()])
        chains["event_participants"].execute.return_value = _result([])
        with svc(mock_sb), pytest.raises(HTTPException) as exc:
            get_invitable_friends(ME, EVENT_ID)
        _assert_error(exc, 403, "not_event_member")


# ---------- get_my_invitations ----------

class TestMyInvitations:
    def test_lists_each_invitation_with_total_and_purges_stale(self):
        from app.services.invitation_service import get_my_invitations
        mock_sb, chains = make_table_router()
        chains["event_invitations"].execute.side_effect = [
            # purge: one upcoming, one started, one cancelled
            _result([
                {"id": 1, "events": {"start_datetime": _future(), "status": "active"}},
                {"id": 2, "events": {"start_datetime": _past(), "status": "active"}},
                {"id": 3, "events": {"start_datetime": _future(), "status": "cancelled"}},
            ]),
            _result([]),  # delete of stale rows
            _result([
                {"id": 5, "event_id": EVENT_ID, "inviter_id": FRIEND, "created_at": "t2",
                 "events": {"id": EVENT_ID, "title": "Beach Volleyball", "start_datetime": "s"}},
                {"id": 1, "event_id": EVENT_ID, "inviter_id": OTHER, "created_at": "t1",
                 "events": {"id": EVENT_ID, "title": "Beach Volleyball", "start_datetime": "s"}},
            ], count=2),
        ]
        with svc(mock_sb):
            result = get_my_invitations(ME, 1, 20)

        chains["event_invitations"].in_.assert_called_once_with("id", [2, 3])
        assert result["total"] == 2
        assert [i["invitation_id"] for i in result["data"]] == [5, 1]
        assert result["data"][0]["inviter"]["id"] == FRIEND
        assert result["data"][0]["event"] == {"id": EVENT_ID, "title": "Beach Volleyball", "start_datetime": "s"}


# ---------- dismiss_invitation ----------

class TestDismiss:
    def test_invited_user_dismisses(self):
        from app.services.invitation_service import dismiss_invitation
        mock_sb, chains = make_table_router()
        chains["event_invitations"].execute.return_value = _result([{"id": 9}])
        with svc(mock_sb):
            assert dismiss_invitation(FRIEND, 9) == {"message": "Invitation dismissed"}
        chains["event_invitations"].eq.assert_any_call("id", 9)
        chains["event_invitations"].eq.assert_any_call("invitee_id", FRIEND)

    def test_someone_else_cannot_dismiss(self):
        from app.services.invitation_service import dismiss_invitation
        mock_sb, chains = make_table_router()
        chains["event_invitations"].execute.return_value = _result([])
        with svc(mock_sb), pytest.raises(HTTPException) as exc:
            dismiss_invitation(ME, 9)
        _assert_error(exc, 404, "invitation_not_found")


# ---------- get_invitation_summary ----------

class TestInvitationSummary:
    def test_first_inviter_and_number_of_others(self):
        from app.services.invitation_service import get_invitation_summary
        mock_sb, chains = make_table_router()
        chains["event_invitations"].execute.return_value = _result(
            [{"inviter_id": FRIEND, "created_at": "t1"}, {"inviter_id": OTHER, "created_at": "t2"},
             {"inviter_id": ORGANIZER, "created_at": "t3"}])
        with svc(mock_sb):
            summary = get_invitation_summary(ME, _event())
        assert summary["invited"] is True
        assert summary["invited_by"]["id"] == FRIEND
        assert summary["other_inviters_count"] == 2

    def test_not_invited(self):
        from app.services.invitation_service import get_invitation_summary
        mock_sb, chains = make_table_router()
        chains["event_invitations"].execute.return_value = _result([])
        with svc(mock_sb):
            assert get_invitation_summary(ME, _event()) == {
                "invited": False, "invited_by": None, "other_inviters_count": 0}

    def test_started_event_shows_no_invitation(self):
        from app.services.invitation_service import get_invitation_summary
        mock_sb, chains = make_table_router()
        with svc(mock_sb):
            assert get_invitation_summary(ME, _event(start=_past()))["invited"] is False
        mock_sb.table.assert_not_called()


# ---------- remove_invitations_for_block ----------

def test_block_cleanup_calls_database_function():
    from app.services.invitation_service import remove_invitations_for_block
    mock_sb = MagicMock()
    with patch(f"{MOD}.supabase", mock_sb):
        remove_invitations_for_block(ME, FRIEND)
    mock_sb.rpc.assert_called_once_with("remove_invitations_for_block", {"user_a": ME, "user_b": FRIEND})


# ---------- routes ----------

class TestRoutes:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.core.dependencies import get_current_onboarded_user

        class User:
            id = ME

        app.dependency_overrides[get_current_onboarded_user] = lambda: User()
        yield TestClient(app)
        app.dependency_overrides.pop(get_current_onboarded_user, None)

    def test_send_passes_ids(self, client):
        with patch("app.api.v1.invitation_routes.invite_friend") as invite:
            invite.return_value = {"invitation_id": 9, "event_id": EVENT_ID, "created_at": "t",
                                   "user": {"id": FRIEND}}
            res = client.post("/api/invitations", json={"event_id": EVENT_ID, "invitee_id": FRIEND})
        assert res.status_code == 201
        invite.assert_called_once_with(ME, EVENT_ID, FRIEND)

    def test_send_rejects_bad_ids(self, client):
        res = client.post("/api/invitations", json={"event_id": "x", "invitee_id": FRIEND})
        assert res.status_code == 422

    def test_dismiss_uses_signed_in_user(self, client):
        with patch("app.api.v1.invitation_routes.dismiss_invitation",
                   return_value={"message": "Invitation dismissed"}) as dismiss:
            res = client.delete("/api/invitations/9")
        assert res.status_code == 200
        dismiss.assert_called_once_with(ME, 9)

    def test_event_details_adds_invitation_only_when_signed_in(self, client):
        from app.main import app
        from app.core.dependencies import get_optional_user

        class User:
            id = ME

        summary = {"invited": True, "invited_by": {"id": FRIEND}, "other_inviters_count": 0}
        with patch("app.api.v1.event_routes.get_event", side_effect=lambda _id: _event()), \
             patch("app.api.v1.event_routes.attach_organizers"), \
             patch("app.api.v1.event_routes.get_invitation_summary", return_value=summary):
            anonymous = client.get(f"/api/events/{EVENT_ID}").json()
            app.dependency_overrides[get_optional_user] = lambda: User()
            try:
                signed_in = client.get(f"/api/events/{EVENT_ID}").json()
            finally:
                app.dependency_overrides.pop(get_optional_user, None)

        assert "invitation" not in anonymous
        assert anonymous["title"] == "Beach Volleyball"
        assert signed_in["invitation"] == summary


        

# ---------- purge_started_invitations (#207) ----------

class TestPurgeStartedInvitations:
    def test_deletes_invitations_to_started_events(self):
        from app.services.invitation_service import purge_started_invitations
        mock_sb, chains = make_table_router()
        chains["event_invitations"].execute.side_effect = [
            _result([{"id": 4, "events": {"start_datetime": _past()}},
                     {"id": 7, "events": {"start_datetime": _past(2)}}]),
            _result([]),  # delete
        ]
        with svc(mock_sb):
            deleted = purge_started_invitations()

        assert deleted == 2
        # only events whose start is at or before now are selected
        field, value = chains["event_invitations"].lte.call_args.args
        assert field == "events.start_datetime"
        assert datetime.fromisoformat(value) <= datetime.now(timezone.utc)
        chains["event_invitations"].delete.assert_called_once()
        chains["event_invitations"].in_.assert_called_once_with("id", [4, 7])

    def test_nothing_to_delete_makes_no_delete_call(self):
        from app.services.invitation_service import purge_started_invitations
        mock_sb, chains = make_table_router()
        chains["event_invitations"].execute.return_value = _result([])
        with svc(mock_sb):
            assert purge_started_invitations() == 0
        chains["event_invitations"].delete.assert_not_called()

    def test_scheduler_entry_point_swallows_errors(self):
        from app.services.invitation_service import run_invitation_purge
        with patch(f"{MOD}.purge_started_invitations", side_effect=RuntimeError("db down")):
            run_invitation_purge()  # must not raise, or the scheduler job dies


class TestPurgeIsWired:
    def test_get_notifications_purges_users_stale_invitations_first(self):
        from app.services import notification_service
        mock_sb = MagicMock()
        chain = mock_sb.table.return_value
        for m in ("select", "eq", "order", "range"):
            getattr(chain, m).return_value = chain
        chain.execute.return_value = _result([])
        with patch(f"{MOD}._purge_stale_invitations") as purge, \
             patch.object(notification_service, "supabase", mock_sb):
            notification_service.get_notifications(ME, 1, 10)
        purge.assert_called_once_with(ME)

    def test_get_notifications_still_works_when_purge_fails(self):
        from app.services import notification_service
        mock_sb = MagicMock()
        chain = mock_sb.table.return_value
        for m in ("select", "eq", "order", "range"):
            getattr(chain, m).return_value = chain
        chain.execute.return_value = _result([])
        with patch(f"{MOD}._purge_stale_invitations", side_effect=RuntimeError("db down")), \
             patch.object(notification_service, "supabase", mock_sb):
            result = notification_service.get_notifications(ME, 1, 10)
        assert result["data"] == []

    def test_cron_trigger_runs_purge(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.core.config import settings
        with patch(f"{MOD}.run_invitation_purge") as purge, \
             patch("app.services.reminder_service.send_event_reminders"), \
             patch.object(settings, "CRON_SECRET", "s3cret"):
            response = TestClient(app).post("/api/reminders/trigger", headers={"x-cron-secret": "s3cret"})
        assert response.status_code == 200
        purge.assert_called_once()