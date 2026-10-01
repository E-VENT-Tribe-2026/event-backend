import pytest
from contextlib import contextmanager, ExitStack
from unittest.mock import MagicMock, call, patch
from fastapi import HTTPException

from tests._supabase_mock import make_table_router

ME = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
STRANGER = "33333333-3333-4333-8333-333333333333"
MOD = "app.services.friendship_service"


class UniqueViolation(Exception):
    code = "23505"


def _summaries(ids):
    return {i: {"id": i, "username": f"user_{i[:4]}"} for i in ids}


@contextmanager
def svc(mock_sb, state=False):
    """Patches supabase and the cross-module collaborators of friendship_service."""
    names = ["get_user_summaries", "get_username", "create_notification", "delete_notifications_for"]
    if state:
        names.append("get_friendship_state")
    with ExitStack() as stack:
        stack.enter_context(patch(f"{MOD}.supabase", mock_sb))
        mocks = {n: stack.enter_context(patch(f"{MOD}.{n}")) for n in names}
        mocks["get_user_summaries"].side_effect = _summaries
        mocks["get_username"].side_effect = lambda uid: {ME: "john_42", OTHER: "jane_doe"}.get(uid, "someone")
        yield mocks


def _req(rid=7, initiator=ME, receiver=OTHER):
    return {"id": rid, "initiator_id": initiator, "receiver_id": receiver,
            "status": "pending", "created_at": "2026-01-01T10:00:00+00:00"}


def _friendship(a=ME, b=OTHER):
    return {"id": 1, "user_id": a, "friend_id": b, "created_at": "2026-02-02T10:00:00+00:00"}


def _assert_friendship_query(mock_sb, chains, a, b):
    mock_sb.table.assert_any_call("friendships")
    pair = chains["friendships"].or_.call_args[0][0]
    assert f"and(user_id.eq.{a},friend_id.eq.{b})" in pair
    assert f"and(user_id.eq.{b},friend_id.eq.{a})" in pair


def _assert_request_query(mock_sb, chains, a, b):
    mock_sb.table.assert_any_call("friend_requests")
    chains["friend_requests"].eq.assert_any_call("status", "pending")
    pair = chains["friend_requests"].or_.call_args[0][0]
    assert f"and(initiator_id.eq.{a},receiver_id.eq.{b})" in pair
    assert f"and(initiator_id.eq.{b},receiver_id.eq.{a})" in pair


# ────────────────────────────────────────────────────────────────────────────
# get_friendship_state
# ────────────────────────────────────────────────────────────────────────────

class TestGetFriendshipState:
    def test_self_makes_no_queries(self):
        mock_sb, chains = make_table_router()
        with svc(mock_sb):
            from app.services.friendship_service import get_friendship_state
            assert get_friendship_state(ME, ME) == {"status": "self", "request_id": None}
        mock_sb.table.assert_not_called()

    def test_self_case_differing_uuid_makes_no_queries(self):
        mock_sb, chains = make_table_router()
        with svc(mock_sb):
            from app.services.friendship_service import get_friendship_state
            assert get_friendship_state(ME, f" {ME.upper()} ")["status"] == "self"
        mock_sb.table.assert_not_called()

    def test_friends(self):
        mock_sb, chains = make_table_router()
        chains["friendships"].execute.return_value = MagicMock(data=[_friendship()])
        with svc(mock_sb):
            from app.services.friendship_service import get_friendship_state
            assert get_friendship_state(ME, OTHER) == {"status": "friends", "request_id": None}
        chains["friend_requests"].execute.assert_not_called()
        _assert_friendship_query(mock_sb, chains, ME, OTHER)

    def test_request_sent(self):
        mock_sb, chains = make_table_router()
        chains["friendships"].execute.return_value = MagicMock(data=[])
        chains["friend_requests"].execute.return_value = MagicMock(data=[_req(9, ME, OTHER)])
        with svc(mock_sb):
            from app.services.friendship_service import get_friendship_state
            assert get_friendship_state(ME, OTHER) == {"status": "request_sent", "request_id": 9}
        _assert_friendship_query(mock_sb, chains, ME, OTHER)
        _assert_request_query(mock_sb, chains, ME, OTHER)

    def test_request_received(self):
        mock_sb, chains = make_table_router()
        chains["friendships"].execute.return_value = MagicMock(data=[])
        chains["friend_requests"].execute.return_value = MagicMock(data=[_req(11, OTHER, ME)])
        with svc(mock_sb):
            from app.services.friendship_service import get_friendship_state
            assert get_friendship_state(ME, OTHER) == {"status": "request_received", "request_id": 11}
        _assert_request_query(mock_sb, chains, ME, OTHER)

    def test_request_direction_resolves_per_viewer(self):
        mock_sb, chains = make_table_router()
        chains["friendships"].execute.return_value = MagicMock(data=[])
        chains["friend_requests"].execute.return_value = MagicMock(data=[_req(9, ME, OTHER)])
        with svc(mock_sb):
            from app.services.friendship_service import get_friendship_state
            assert get_friendship_state(ME, OTHER) == {"status": "request_sent", "request_id": 9}
            assert get_friendship_state(OTHER, ME) == {"status": "request_received", "request_id": 9}

    def test_non_uuid_other_returns_none_without_queries(self):
        mock_sb, chains = make_table_router()
        with svc(mock_sb):
            from app.services.friendship_service import get_friendship_state
            assert get_friendship_state(ME, "x),user_id.not.is.null") == {"status": "none", "request_id": None}
        mock_sb.table.assert_not_called()

    def test_none(self):
        mock_sb, chains = make_table_router()
        chains["friendships"].execute.return_value = MagicMock(data=[])
        chains["friend_requests"].execute.return_value = MagicMock(data=[])
        with svc(mock_sb):
            from app.services.friendship_service import get_friendship_state
            assert get_friendship_state(ME, OTHER) == {"status": "none", "request_id": None}
        _assert_friendship_query(mock_sb, chains, ME, OTHER)
        _assert_request_query(mock_sb, chains, ME, OTHER)


class TestPairFilter:
    def test_both_directions(self):
        from app.services.friendship_service import _pair_filter
        assert _pair_filter(ME, OTHER, "user_id", "friend_id") == (
            f"and(user_id.eq.{ME},friend_id.eq.{OTHER}),and(user_id.eq.{OTHER},friend_id.eq.{ME})")

    def test_canonicalises_case(self):
        from app.services.friendship_service import _pair_filter
        assert ME in _pair_filter(ME.upper(), OTHER, "a", "b")

    @pytest.mark.parametrize("bad", ["x),user_id.not.is.null,and(user_id.eq.x", "u1", "", None])
    def test_non_uuid_raises(self, bad):
        from app.services.friendship_service import _pair_filter
        with pytest.raises(ValueError):
            _pair_filter(ME, bad, "user_id", "friend_id")
        with pytest.raises(ValueError):
            _pair_filter(bad, ME, "user_id", "friend_id")


# ────────────────────────────────────────────────────────────────────────────
# send_friend_request
# ────────────────────────────────────────────────────────────────────────────

class TestSendFriendRequest:
    def test_success(self):
        mock_sb, chains = make_table_router()
        chains["profiles"].execute.return_value = MagicMock(data=[{"id": OTHER}])
        chains["friend_requests"].execute.return_value = MagicMock(data=[_req(7)])
        with svc(mock_sb, state=True) as m:
            m["get_friendship_state"].return_value = {"status": "none", "request_id": None}
            from app.services.friendship_service import send_friend_request
            result = send_friend_request(ME, OTHER)

        assert chains["friend_requests"].insert.call_args[0][0] == {
            "initiator_id": ME, "receiver_id": OTHER, "status": "pending"}
        m["create_notification"].assert_called_once_with(
            OTHER, None, "friend_request_received", "john_42 sent you a friend request",
            related_user_id=ME)
        assert result == {
            "request_id": 7,
            "created_at": "2026-01-01T10:00:00+00:00",
            "user": {"id": OTHER, "username": f"user_{OTHER[:4]}"},
        }
        m["get_user_summaries"].assert_called_once_with([OTHER])

    def test_self_raises_400(self):
        mock_sb, chains = make_table_router()
        with svc(mock_sb):
            from app.services.friendship_service import send_friend_request
            with pytest.raises(HTTPException) as exc:
                send_friend_request(ME, ME)
        assert exc.value.status_code == 400
        assert exc.value.detail["code"] == "cannot_friend_self"
        mock_sb.table.assert_not_called()

    def test_self_uppercase_raises_400(self):
        mock_sb, chains = make_table_router()
        with svc(mock_sb):
            from app.services.friendship_service import send_friend_request
            with pytest.raises(HTTPException) as exc:
                send_friend_request(ME, ME.upper())
        assert exc.value.status_code == 400
        assert exc.value.detail["code"] == "cannot_friend_self"

    def test_unknown_user_raises_404(self):
        mock_sb, chains = make_table_router()
        chains["profiles"].execute.return_value = MagicMock(data=[])
        with svc(mock_sb, state=True) as m:
            from app.services.friendship_service import send_friend_request
            with pytest.raises(HTTPException) as exc:
                send_friend_request(ME, OTHER)
        assert exc.value.status_code == 404
        assert exc.value.detail["code"] == "user_not_found"
        chains["friend_requests"].insert.assert_not_called()
        m["create_notification"].assert_not_called()

    @pytest.mark.parametrize("status,request_id,code", [
        ("friends", None, "already_friends"),
        ("request_sent", 5, "request_already_sent"),
        ("request_received", 6, "request_already_received"),
    ])
    def test_conflicting_state_raises_409(self, status, request_id, code):
        mock_sb, chains = make_table_router()
        chains["profiles"].execute.return_value = MagicMock(data=[{"id": OTHER}])
        with svc(mock_sb, state=True) as m:
            m["get_friendship_state"].return_value = {"status": status, "request_id": request_id}
            from app.services.friendship_service import send_friend_request
            with pytest.raises(HTTPException) as exc:
                send_friend_request(ME, OTHER)
        assert exc.value.status_code == 409
        assert exc.value.detail["code"] == code
        assert exc.value.detail["request_id"] == request_id
        chains["friend_requests"].insert.assert_not_called()
        m["create_notification"].assert_not_called()

    @pytest.mark.parametrize("state,code,request_id", [
        ({"status": "request_sent", "request_id": 5}, "request_already_sent", 5),
        ({"status": "request_received", "request_id": 6}, "request_already_received", 6),
        ({"status": "friends", "request_id": None}, "already_friends", None),
    ])
    def test_unique_violation_maps_to_409(self, state, code, request_id):
        mock_sb, chains = make_table_router()
        chains["profiles"].execute.return_value = MagicMock(data=[{"id": OTHER}])
        chains["friend_requests"].execute.side_effect = [UniqueViolation("duplicate key")]
        with svc(mock_sb, state=True) as m:
            m["get_friendship_state"].side_effect = [
                {"status": "none", "request_id": None}, state]
            from app.services.friendship_service import send_friend_request
            with pytest.raises(HTTPException) as exc:
                send_friend_request(ME, OTHER)
        assert exc.value.status_code == 409
        assert exc.value.detail["code"] == code
        assert exc.value.detail["request_id"] == request_id
        m["create_notification"].assert_not_called()

    def test_unique_violation_with_state_none_reraises_original(self):
        mock_sb, chains = make_table_router()
        chains["profiles"].execute.return_value = MagicMock(data=[{"id": OTHER}])
        original = UniqueViolation("duplicate key")
        chains["friend_requests"].execute.side_effect = [original]
        with svc(mock_sb, state=True) as m:
            m["get_friendship_state"].return_value = {"status": "none", "request_id": None}
            from app.services.friendship_service import send_friend_request
            with pytest.raises(UniqueViolation) as exc:
                send_friend_request(ME, OTHER)
        assert exc.value is original

    def test_notification_failure_does_not_fail_send(self):
        mock_sb, chains = make_table_router()
        chains["profiles"].execute.return_value = MagicMock(data=[{"id": OTHER}])
        chains["friend_requests"].execute.return_value = MagicMock(data=[_req(7)])
        with svc(mock_sb, state=True) as m:
            m["get_friendship_state"].return_value = {"status": "none", "request_id": None}
            m["create_notification"].side_effect = RuntimeError("boom")
            from app.services.friendship_service import send_friend_request
            result = send_friend_request(ME, OTHER)
        assert result["request_id"] == 7


# ────────────────────────────────────────────────────────────────────────────
# cancel_friend_request
# ────────────────────────────────────────────────────────────────────────────

class TestCancelFriendRequest:
    def test_success(self):
        mock_sb, chains = make_table_router()
        chains["friend_requests"].execute.side_effect = [
            MagicMock(data=[_req(7, ME, OTHER)]), MagicMock(data=[_req(7)])]
        with svc(mock_sb) as m:
            from app.services.friendship_service import cancel_friend_request
            result = cancel_friend_request(7, ME)
        assert result == {"message": "Friend request cancelled"}
        chains["friend_requests"].delete.assert_called_once()
        chains["friend_requests"].eq.assert_any_call("id", 7)
        chains["friend_requests"].eq.assert_any_call("initiator_id", ME)
        chains["friend_requests"].eq.assert_any_call("status", "pending")
        m["delete_notifications_for"].assert_called_once_with(OTHER, "friend_request_received", ME)

    def test_cleanup_failure_does_not_fail(self):
        mock_sb, chains = make_table_router()
        chains["friend_requests"].execute.side_effect = [
            MagicMock(data=[_req(7, ME, OTHER)]), MagicMock(data=[_req(7)])]
        with svc(mock_sb) as m:
            m["delete_notifications_for"].side_effect = RuntimeError("boom")
            from app.services.friendship_service import cancel_friend_request
            assert cancel_friend_request(7, ME) == {"message": "Friend request cancelled"}

    def test_lost_claim_raises_404_without_cleanup(self):
        mock_sb, chains = make_table_router()
        chains["friend_requests"].execute.side_effect = [
            MagicMock(data=[_req(7, ME, OTHER)]), MagicMock(data=[])]
        with svc(mock_sb) as m:
            from app.services.friendship_service import cancel_friend_request
            with pytest.raises(HTTPException) as exc:
                cancel_friend_request(7, ME)
        assert exc.value.status_code == 404
        assert exc.value.detail["code"] == "request_not_found"
        m["delete_notifications_for"].assert_not_called()

    def test_recipient_gets_403(self):
        mock_sb, chains = make_table_router()
        chains["friend_requests"].execute.side_effect = [MagicMock(data=[_req(7, ME, OTHER)])]
        with svc(mock_sb) as m:
            from app.services.friendship_service import cancel_friend_request
            with pytest.raises(HTTPException) as exc:
                cancel_friend_request(7, OTHER)
        assert exc.value.status_code == 403
        assert exc.value.detail["code"] == "not_request_sender"
        chains["friend_requests"].delete.assert_not_called()
        m["delete_notifications_for"].assert_not_called()

    def test_stranger_gets_404(self):
        mock_sb, chains = make_table_router()
        chains["friend_requests"].execute.side_effect = [MagicMock(data=[_req(7, ME, OTHER)])]
        with svc(mock_sb):
            from app.services.friendship_service import cancel_friend_request
            with pytest.raises(HTTPException) as exc:
                cancel_friend_request(7, STRANGER)
        assert exc.value.status_code == 404
        assert exc.value.detail["code"] == "request_not_found"
        chains["friend_requests"].delete.assert_not_called()

    def test_non_existent_gets_404(self):
        mock_sb, chains = make_table_router()
        chains["friend_requests"].execute.side_effect = [MagicMock(data=[])]
        with svc(mock_sb):
            from app.services.friendship_service import cancel_friend_request
            with pytest.raises(HTTPException) as exc:
                cancel_friend_request(999, ME)
        assert exc.value.status_code == 404
        assert exc.value.detail["code"] == "request_not_found"
        chains["friend_requests"].eq.assert_any_call("status", "pending")


# ────────────────────────────────────────────────────────────────────────────
# accept_friend_request
# ────────────────────────────────────────────────────────────────────────────

class TestAcceptFriendRequest:
    def test_success(self):
        mock_sb, chains = make_table_router()
        chains["friend_requests"].execute.side_effect = [
            MagicMock(data=[_req(7, ME, OTHER)]), MagicMock(data=[_req(7)])]
        chains["friendships"].execute.return_value = MagicMock(data=[_friendship(ME, OTHER)])
        with svc(mock_sb) as m:
            from app.services.friendship_service import accept_friend_request
            result = accept_friend_request(7, OTHER)

        assert chains["friendships"].insert.call_args[0][0] == {
            "user_id": ME, "friend_id": OTHER, "origin": ME, "status": "active"}
        chains["friend_requests"].delete.assert_called_once()
        chains["friend_requests"].eq.assert_any_call("id", 7)
        chains["friend_requests"].eq.assert_any_call("receiver_id", OTHER)
        chains["friend_requests"].eq.assert_any_call("status", "pending")
        m["delete_notifications_for"].assert_called_once_with(OTHER, "friend_request_received", ME)
        m["create_notification"].assert_called_once_with(
            ME, None, "friend_request_accepted", "jane_doe accepted your friend request",
            related_user_id=OTHER)
        assert result == {
            "friend_since": "2026-02-02T10:00:00+00:00",
            "user": {"id": ME, "username": f"user_{ME[:4]}"},
        }

    def test_sender_gets_403(self):
        mock_sb, chains = make_table_router()
        chains["friend_requests"].execute.side_effect = [MagicMock(data=[_req(7, ME, OTHER)])]
        with svc(mock_sb) as m:
            from app.services.friendship_service import accept_friend_request
            with pytest.raises(HTTPException) as exc:
                accept_friend_request(7, ME)
        assert exc.value.status_code == 403
        assert exc.value.detail["code"] == "not_request_receiver"
        chains["friendships"].insert.assert_not_called()
        m["create_notification"].assert_not_called()

    def test_stranger_gets_404(self):
        mock_sb, chains = make_table_router()
        chains["friend_requests"].execute.side_effect = [MagicMock(data=[_req(7, ME, OTHER)])]
        with svc(mock_sb):
            from app.services.friendship_service import accept_friend_request
            with pytest.raises(HTTPException) as exc:
                accept_friend_request(7, STRANGER)
        assert exc.value.status_code == 404
        assert exc.value.detail["code"] == "request_not_found"
        chains["friendships"].insert.assert_not_called()

    def test_existing_friendship_unique_violation_still_cleans_up(self):
        mock_sb, chains = make_table_router()
        chains["friend_requests"].execute.side_effect = [
            MagicMock(data=[_req(7, ME, OTHER)]), MagicMock(data=[_req(7)])]
        chains["friendships"].execute.side_effect = [
            UniqueViolation("duplicate key"), MagicMock(data=[_friendship(OTHER, ME)])]
        with svc(mock_sb) as m:
            from app.services.friendship_service import accept_friend_request
            result = accept_friend_request(7, OTHER)

        chains["friend_requests"].delete.assert_called_once()
        chains["friend_requests"].eq.assert_any_call("receiver_id", OTHER)
        m["delete_notifications_for"].assert_called_once_with(OTHER, "friend_request_received", ME)
        m["create_notification"].assert_not_called()
        assert result["friend_since"] == "2026-02-02T10:00:00+00:00"
        assert result["user"]["id"] == ME

    def test_lost_claim_raises_404_and_creates_no_friendship(self):
        mock_sb, chains = make_table_router()
        chains["friend_requests"].execute.side_effect = [
            MagicMock(data=[_req(7, ME, OTHER)]), MagicMock(data=[])]
        with svc(mock_sb) as m:
            from app.services.friendship_service import accept_friend_request
            with pytest.raises(HTTPException) as exc:
                accept_friend_request(7, OTHER)
        assert exc.value.status_code == 404
        assert exc.value.detail["code"] == "request_not_found"
        chains["friendships"].insert.assert_not_called()
        m["delete_notifications_for"].assert_not_called()
        m["create_notification"].assert_not_called()

    def test_unique_violation_without_existing_friendship_reraises(self):
        mock_sb, chains = make_table_router()
        chains["friend_requests"].execute.side_effect = [
            MagicMock(data=[_req(7, ME, OTHER)]), MagicMock(data=[_req(7)])]
        original = UniqueViolation("duplicate key")
        chains["friendships"].execute.side_effect = [original, MagicMock(data=[])]
        with svc(mock_sb):
            from app.services.friendship_service import accept_friend_request
            with pytest.raises(UniqueViolation) as exc:
                accept_friend_request(7, OTHER)
        assert exc.value is original

    def test_insert_failure_restores_request_and_reraises(self):
        mock_sb, chains = make_table_router()
        chains["friend_requests"].execute.side_effect = [
            MagicMock(data=[_req(7, ME, OTHER)]), MagicMock(data=[_req(7)]), MagicMock(data=[_req(7)])]
        boom = RuntimeError("db down")
        chains["friendships"].execute.side_effect = [boom]
        with svc(mock_sb) as m:
            from app.services.friendship_service import accept_friend_request
            with pytest.raises(RuntimeError) as exc:
                accept_friend_request(7, OTHER)
        assert exc.value is boom
        assert chains["friend_requests"].insert.call_args[0][0] == {
            "id": 7, "initiator_id": ME, "receiver_id": OTHER,
            "status": "pending", "created_at": "2026-01-01T10:00:00+00:00"}
        m["create_notification"].assert_not_called()
        m["delete_notifications_for"].assert_not_called()

    def test_restore_failure_still_reraises_original(self):
        mock_sb, chains = make_table_router()
        chains["friend_requests"].execute.side_effect = [
            MagicMock(data=[_req(7, ME, OTHER)]), MagicMock(data=[_req(7)]), RuntimeError("restore failed")]
        boom = RuntimeError("db down")
        chains["friendships"].execute.side_effect = [boom]
        with svc(mock_sb):
            from app.services.friendship_service import accept_friend_request
            with pytest.raises(RuntimeError) as exc:
                accept_friend_request(7, OTHER)
        assert exc.value is boom

    def test_notification_failures_do_not_fail_accept(self):
        mock_sb, chains = make_table_router()
        chains["friend_requests"].execute.side_effect = [
            MagicMock(data=[_req(7, ME, OTHER)]), MagicMock(data=[_req(7)])]
        chains["friendships"].execute.return_value = MagicMock(data=[_friendship(ME, OTHER)])
        with svc(mock_sb) as m:
            m["delete_notifications_for"].side_effect = RuntimeError("boom")
            m["create_notification"].side_effect = RuntimeError("boom")
            from app.services.friendship_service import accept_friend_request
            result = accept_friend_request(7, OTHER)
        assert result["user"]["id"] == ME


# ────────────────────────────────────────────────────────────────────────────
# decline_friend_request
# ────────────────────────────────────────────────────────────────────────────

class TestDeclineFriendRequest:
    def test_success_never_notifies(self):
        mock_sb, chains = make_table_router()
        chains["friend_requests"].execute.side_effect = [
            MagicMock(data=[_req(7, ME, OTHER)]), MagicMock(data=[_req(7)])]
        with svc(mock_sb) as m:
            from app.services.friendship_service import decline_friend_request
            result = decline_friend_request(7, OTHER)
        assert result == {"message": "Friend request declined"}
        chains["friend_requests"].delete.assert_called_once()
        chains["friend_requests"].eq.assert_any_call("id", 7)
        chains["friend_requests"].eq.assert_any_call("receiver_id", OTHER)
        chains["friend_requests"].eq.assert_any_call("status", "pending")
        m["delete_notifications_for"].assert_called_once_with(OTHER, "friend_request_received", ME)
        m["create_notification"].assert_not_called()

    def test_lost_claim_raises_404_without_cleanup(self):
        mock_sb, chains = make_table_router()
        chains["friend_requests"].execute.side_effect = [
            MagicMock(data=[_req(7, ME, OTHER)]), MagicMock(data=[])]
        with svc(mock_sb) as m:
            from app.services.friendship_service import decline_friend_request
            with pytest.raises(HTTPException) as exc:
                decline_friend_request(7, OTHER)
        assert exc.value.status_code == 404
        assert exc.value.detail["code"] == "request_not_found"
        m["delete_notifications_for"].assert_not_called()
        m["create_notification"].assert_not_called()

    def test_sender_gets_403(self):
        mock_sb, chains = make_table_router()
        chains["friend_requests"].execute.side_effect = [MagicMock(data=[_req(7, ME, OTHER)])]
        with svc(mock_sb) as m:
            from app.services.friendship_service import decline_friend_request
            with pytest.raises(HTTPException) as exc:
                decline_friend_request(7, ME)
        assert exc.value.status_code == 403
        assert exc.value.detail["code"] == "not_request_receiver"
        chains["friend_requests"].delete.assert_not_called()
        m["create_notification"].assert_not_called()

    def test_stranger_gets_404(self):
        mock_sb, chains = make_table_router()
        chains["friend_requests"].execute.side_effect = [MagicMock(data=[_req(7, ME, OTHER)])]
        with svc(mock_sb):
            from app.services.friendship_service import decline_friend_request
            with pytest.raises(HTTPException) as exc:
                decline_friend_request(7, STRANGER)
        assert exc.value.status_code == 404
        assert exc.value.detail["code"] == "request_not_found"

    def test_cleanup_failure_does_not_fail(self):
        mock_sb, chains = make_table_router()
        chains["friend_requests"].execute.side_effect = [
            MagicMock(data=[_req(7, ME, OTHER)]), MagicMock(data=[_req(7)])]
        with svc(mock_sb) as m:
            m["delete_notifications_for"].side_effect = RuntimeError("boom")
            from app.services.friendship_service import decline_friend_request
            assert decline_friend_request(7, OTHER) == {"message": "Friend request declined"}


# ────────────────────────────────────────────────────────────────────────────
# incoming / sent / count
# ────────────────────────────────────────────────────────────────────────────

class TestIncomingRequests:
    def test_query_and_shape_uses_initiator_as_other_party(self):
        mock_sb, chains = make_table_router()
        chains["friend_requests"].execute.return_value = MagicMock(data=[
            _req(2, OTHER, ME), _req(1, STRANGER, ME)])
        with svc(mock_sb) as m:
            from app.services.friendship_service import get_incoming_requests
            result = get_incoming_requests(ME)

        chains["friend_requests"].eq.assert_any_call("receiver_id", ME)
        chains["friend_requests"].eq.assert_any_call("status", "pending")
        chains["friend_requests"].order.assert_has_calls([call("created_at", desc=True), call("id", desc=True)])
        chains["friend_requests"].range.assert_called_once_with(0, 20)
        m["get_user_summaries"].assert_called_once()
        assert sorted(m["get_user_summaries"].call_args[0][0]) == sorted([OTHER, STRANGER])
        assert result["page"] == 1 and result["limit"] == 20 and result["has_more"] is False
        assert [i["request_id"] for i in result["data"]] == [2, 1]
        assert result["data"][0]["user"]["id"] == OTHER
        assert result["data"][0]["created_at"] == "2026-01-01T10:00:00+00:00"
        assert result["data"][1]["user"]["id"] == STRANGER

    def test_has_more_true_and_trimmed(self):
        mock_sb, chains = make_table_router()
        chains["friend_requests"].execute.return_value = MagicMock(data=[
            _req(3, OTHER, ME), _req(2, STRANGER, ME), _req(1, OTHER, ME)])
        with svc(mock_sb):
            from app.services.friendship_service import get_incoming_requests
            result = get_incoming_requests(ME, page=2, limit=2)
        chains["friend_requests"].range.assert_called_once_with(2, 4)
        assert result["has_more"] is True
        assert len(result["data"]) == 2
        assert result["page"] == 2 and result["limit"] == 2

    def test_has_more_false_at_exactly_limit(self):
        mock_sb, chains = make_table_router()
        chains["friend_requests"].execute.return_value = MagicMock(data=[
            _req(2, OTHER, ME), _req(1, STRANGER, ME)])
        with svc(mock_sb):
            from app.services.friendship_service import get_incoming_requests
            result = get_incoming_requests(ME, page=1, limit=2)
        assert result["has_more"] is False
        assert len(result["data"]) == 2


class TestSentRequests:
    def test_query_and_shape_uses_receiver_as_other_party(self):
        mock_sb, chains = make_table_router()
        chains["friend_requests"].execute.return_value = MagicMock(data=[_req(4, ME, OTHER)])
        with svc(mock_sb) as m:
            from app.services.friendship_service import get_sent_requests
            result = get_sent_requests(ME)
        chains["friend_requests"].eq.assert_any_call("initiator_id", ME)
        chains["friend_requests"].eq.assert_any_call("status", "pending")
        chains["friend_requests"].order.assert_has_calls([call("created_at", desc=True), call("id", desc=True)])
        chains["friend_requests"].range.assert_called_once_with(0, 20)
        assert m["get_user_summaries"].call_args[0][0] == [OTHER]
        assert result["data"] == [{
            "request_id": 4,
            "created_at": "2026-01-01T10:00:00+00:00",
            "user": {"id": OTHER, "username": f"user_{OTHER[:4]}"},
        }]
        assert result["has_more"] is False

    def test_has_more_true_and_trimmed(self):
        mock_sb, chains = make_table_router()
        chains["friend_requests"].execute.return_value = MagicMock(data=[
            _req(3, ME, OTHER), _req(2, ME, STRANGER), _req(1, ME, OTHER)])
        with svc(mock_sb):
            from app.services.friendship_service import get_sent_requests
            result = get_sent_requests(ME, page=3, limit=2)
        chains["friend_requests"].range.assert_called_once_with(4, 6)
        assert result["has_more"] is True
        assert len(result["data"]) == 2


class TestCountIncomingRequests:
    def test_returns_count(self):
        mock_sb, chains = make_table_router()
        chains["friend_requests"].execute.return_value = MagicMock(data=[], count=3)
        with svc(mock_sb):
            from app.services.friendship_service import count_incoming_requests
            assert count_incoming_requests(ME) == {"count": 3}
        chains["friend_requests"].select.assert_called_once_with("id", count="exact")
        chains["friend_requests"].eq.assert_any_call("receiver_id", ME)
        chains["friend_requests"].eq.assert_any_call("status", "pending")

    def test_none_count_returns_zero(self):
        mock_sb, chains = make_table_router()
        chains["friend_requests"].execute.return_value = MagicMock(data=[], count=None)
        with svc(mock_sb):
            from app.services.friendship_service import count_incoming_requests
            assert count_incoming_requests(ME) == {"count": 0}


# ────────────────────────────────────────────────────────────────────────────
# get_friends / remove_friend
# ────────────────────────────────────────────────────────────────────────────

class TestGetFriends:
    def test_both_directions_return_other_party(self):
        mock_sb, chains = make_table_router()
        chains["friendships"].execute.return_value = MagicMock(data=[
            {"id": 2, "user_id": ME, "friend_id": OTHER, "created_at": "2026-03-01T00:00:00+00:00"},
            {"id": 1, "user_id": STRANGER, "friend_id": ME, "created_at": "2026-02-01T00:00:00+00:00"},
        ])
        with svc(mock_sb) as m:
            from app.services.friendship_service import get_friends
            result = get_friends(ME)

        chains["friendships"].or_.assert_called_once_with(f"user_id.eq.{ME},friend_id.eq.{ME}")
        chains["friendships"].order.assert_has_calls([call("created_at", desc=True), call("id", desc=True)])
        chains["friendships"].range.assert_called_once_with(0, 20)
        m["get_user_summaries"].assert_called_once()
        assert sorted(m["get_user_summaries"].call_args[0][0]) == sorted([OTHER, STRANGER])
        assert result["page"] == 1 and result["limit"] == 20 and result["has_more"] is False
        assert result["data"][0]["friend_since"] == "2026-03-01T00:00:00+00:00"
        assert result["data"][0]["user"]["id"] == OTHER
        assert result["data"][1]["friend_since"] == "2026-02-01T00:00:00+00:00"
        assert result["data"][1]["user"]["id"] == STRANGER

    def test_non_uuid_user_id_raises_before_querying(self):
        mock_sb, chains = make_table_router()
        with svc(mock_sb):
            from app.services.friendship_service import get_friends
            with pytest.raises(ValueError):
                get_friends("x),user_id.not.is.null")
        mock_sb.table.assert_not_called()

    def test_has_more_true_and_trimmed(self):
        mock_sb, chains = make_table_router()
        chains["friendships"].execute.return_value = MagicMock(data=[
            _friendship(ME, OTHER), _friendship(STRANGER, ME), _friendship(ME, OTHER)])
        with svc(mock_sb):
            from app.services.friendship_service import get_friends
            result = get_friends(ME, page=2, limit=2)
        chains["friendships"].range.assert_called_once_with(2, 4)
        assert result["has_more"] is True
        assert len(result["data"]) == 2

    def test_has_more_false_at_exactly_limit(self):
        mock_sb, chains = make_table_router()
        chains["friendships"].execute.return_value = MagicMock(data=[
            _friendship(ME, OTHER), _friendship(STRANGER, ME)])
        with svc(mock_sb):
            from app.services.friendship_service import get_friends
            result = get_friends(ME, page=1, limit=2)
        assert result["has_more"] is False
        assert len(result["data"]) == 2


class TestRemoveFriend:
    def test_success_filters_both_orders_and_never_notifies(self):
        mock_sb, chains = make_table_router()
        chains["friendships"].execute.return_value = MagicMock(data=[_friendship(OTHER, ME)])
        with svc(mock_sb) as m:
            from app.services.friendship_service import remove_friend
            result = remove_friend(ME, OTHER)
        assert result == {"message": "Friend removed"}
        chains["friendships"].delete.assert_called_once()
        pair = chains["friendships"].or_.call_args[0][0]
        assert f"and(user_id.eq.{ME},friend_id.eq.{OTHER})" in pair
        assert f"and(user_id.eq.{OTHER},friend_id.eq.{ME})" in pair
        m["create_notification"].assert_not_called()
        m["delete_notifications_for"].assert_not_called()

    def test_not_friends_raises_404(self):
        mock_sb, chains = make_table_router()
        chains["friendships"].execute.return_value = MagicMock(data=[])
        with svc(mock_sb) as m:
            from app.services.friendship_service import remove_friend
            with pytest.raises(HTTPException) as exc:
                remove_friend(ME, OTHER)
        assert exc.value.status_code == 404
        assert exc.value.detail["code"] == "friendship_not_found"
        m["create_notification"].assert_not_called()
        m["delete_notifications_for"].assert_not_called()

    @pytest.mark.parametrize("bad", ["x),user_id.not.is.null,and(user_id.eq.x", "requests", ""])
    def test_non_uuid_friend_id_raises_404_without_query(self, bad):
        mock_sb, chains = make_table_router()
        with svc(mock_sb):
            from app.services.friendship_service import remove_friend
            with pytest.raises(HTTPException) as exc:
                remove_friend(ME, bad)
        assert exc.value.status_code == 404
        assert exc.value.detail["code"] == "friendship_not_found"
        mock_sb.table.assert_not_called()
