"""Ticket #234: reporting events, users and chat messages, through direct API requests.

Routes and services run for real against the in-memory Supabase fake (tests/_fake_supabase.py).
Cast: U reports. V is another participant, O organizes the event, X is not in the chat.
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_current_onboarded_user, get_current_user
from app.core.input_limits import REPORT_DESCRIPTION_MAX_LENGTH
from app.core.user_rate_limit import REPORT_LIMIT
from app.main import app
from tests._fake_supabase import FakeSupabase

U = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
V = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
O = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
X = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
ADMIN = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
GHOST = "ffffffff-ffff-4fff-8fff-ffffffffffff"  # has chat messages but no profile row
EVENT = "00000000-0000-4000-8000-00000000000a"
OTHER_EVENT = "00000000-0000-4000-8000-00000000000b"  # organized by U
UNKNOWN = "99999999-9999-4999-8999-999999999999"

client = TestClient(app)
HEADERS = {"Authorization": "Bearer token"}
current = {"id": U}


def _profile(uid, username):
    return {"id": uid, "username": username, "full_name": username.title(), "avatar_kind": "icon", "icon_id": None,
            "avatar_url": None}


@pytest.fixture
def db():
    fake = FakeSupabase()
    fake.tables["profiles"] = [_profile(U, "uma"), _profile(V, "vic"), _profile(O, "olga"), _profile(X, "xena"),
                              {**_profile(ADMIN, "root"), "role": "administrator"}]
    fake.tables["events"] = [
        {"id": EVENT, "created_by": O, "status": "active"},
        {"id": OTHER_EVENT, "created_by": U, "status": "active"},
    ]
    fake.tables["event_participants"] = [
        {"user_id": U, "event_id": EVENT}, {"user_id": V, "event_id": EVENT},
    ]
    # 14 messages in the chat: a system message first, then alternating V and U. Messages of
    # another event are interleaved: they must never end up in a report's chat context.
    fake.add("event_chats", {"event_id": EVENT, "sender_id": None, "type": "notification", "content": "Welcome"})
    for i in range(1, 14):
        fake.add("event_chats", {"event_id": EVENT, "sender_id": V if i % 2 else U, "type": "chat",
                                 "content": f"message {i}"})
        fake.add("event_chats", {"event_id": OTHER_EVENT, "sender_id": V, "type": "chat", "content": f"other {i}"})
    patches = [patch("app.services.report_service.supabase", fake),
               patch("app.core.dependencies.supabase", fake)]
    for p in patches:
        p.start()
    who = lambda: SimpleNamespace(id=current["id"], email="x@y.z")
    app.dependency_overrides[get_current_user] = who
    app.dependency_overrides[get_current_onboarded_user] = who
    current["id"] = U
    yield fake
    for p in patches:
        p.stop()
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_current_onboarded_user, None)


def _msg(db, content):
    return next(m for m in db.tables["event_chats"] if m["content"] == content)


def _break(db, table_name, verb, result):
    """Make one verb on one table fail: result is an exception to raise or a response to return."""
    real_table = db.table

    def table(name):
        query = real_table(name)
        if name == table_name:
            real_verb = getattr(query, verb)

            def broken(*args, **kwargs):
                real_verb(*args, **kwargs)
                if isinstance(result, Exception):
                    query.execute = lambda: (_ for _ in ()).throw(result)
                else:
                    query.execute = lambda: result
                return query

            setattr(query, verb, broken)
        return query

    return patch.object(db, "table", table)


def _admin_dependencies():
    """Use the real onboarding/role checks instead of the test overrides."""
    app.dependency_overrides.pop(get_current_onboarded_user, None)


def post(**overrides):
    body = {"target_type": "event", "target_id": EVENT, "reason": "spam", "origin": "event_details"}
    body.update(overrides)
    return client.post("/api/reports", json=body, headers=HEADERS)


def code(response):
    return response.json()["detail"]["code"]


class TestStoring:
    def test_event_report_is_saved_open_with_confirmation(self, db):
        r = post(description="  Looks fake  ")
        assert r.status_code == 201
        body = r.json()
        assert body["status"] == "open" and body["target_id"] == EVENT and body["message"]
        row = db.tables["reports"][0]
        assert row["reporter_id"] == U and row["target_type"] == "event" and row["event_id"] == EVENT
        assert row["reason"] == "spam" and row["description"] == "Looks fake"
        assert row["origin"] == "event_details" and row["status"] == "open" and row["chat_context"] is None
        assert row["created_at"]

    def test_user_report(self, db):
        r = post(target_type="user", target_id=V, origin="profile", reason="scam_or_fraud")
        assert r.status_code == 201
        row = db.tables["reports"][0]
        assert row["reported_user_id"] == V and row["event_id"] is None and row["message_id"] is None

    def test_message_report_stores_event_message_and_sender(self, db):
        target = _msg(db, "message 5")
        r = post(target_type="message", target_id=target["id"], origin="event_chat", reason="harassment_or_hate")
        assert r.status_code == 201
        row = db.tables["reports"][0]
        assert row["message_id"] == target["id"] and row["event_id"] == EVENT and row["reported_user_id"] == V

    def test_blank_description_is_stored_as_none(self, db):
        assert post(description="   ").status_code == 201
        assert db.tables["reports"][0]["description"] is None


class TestChatContext:
    def test_message_report_carries_five_before_and_five_after(self, db):
        target = _msg(db, "message 7")
        post(target_type="message", target_id=target["id"], origin="event_chat")
        context = db.tables["reports"][0]["chat_context"]
        assert [m["content"] for m in context] == [f"message {i}" for i in range(2, 13)]
        assert [m["id"] for m in context if m["reported"]] == [target["id"]]
        assert context[0]["sender_name"] == "Uma"

    def test_message_near_the_start_has_fewer_before(self, db):
        target = _msg(db, "message 1")
        post(target_type="message", target_id=target["id"], origin="event_chat")
        context = db.tables["reports"][0]["chat_context"]
        assert [m["content"] for m in context] == ["Welcome"] + [f"message {i}" for i in range(1, 7)]
        assert context[0]["sender_name"] == "System"

    def test_event_report_from_chat_carries_last_ten_messages(self, db):
        post(origin="event_chat")
        context = db.tables["reports"][0]["chat_context"]
        assert [m["content"] for m in context] == [f"message {i}" for i in range(4, 14)]

    def test_event_report_from_details_has_no_context(self, db):
        post(origin="event_details")
        assert db.tables["reports"][0]["chat_context"] is None

    def test_context_never_includes_other_events_messages(self, db):
        post(origin="event_chat")
        post(target_type="message", target_id=_msg(db, "message 7")["id"], origin="event_chat")
        for report in db.tables["reports"]:
            assert all(not m["content"].startswith("other") for m in report["chat_context"])

    def test_message_near_the_end_has_fewer_after(self, db):
        post(target_type="message", target_id=_msg(db, "message 13")["id"], origin="event_chat")
        context = db.tables["reports"][0]["chat_context"]
        assert [m["content"] for m in context] == [f"message {i}" for i in range(8, 14)]
        assert context[-1]["reported"] is True

    def test_organizer_can_report_a_message_in_their_own_chat(self, db):
        current["id"] = O
        r = post(target_type="message", target_id=_msg(db, "message 1")["id"], origin="event_chat")
        assert r.status_code == 201
        assert db.tables["reports"][0]["reported_user_id"] == V

    def test_context_is_a_copy_made_at_report_time(self, db):
        post(origin="event_chat")
        _msg(db, "message 13")["content"] = "edited"
        assert db.tables["reports"][0]["chat_context"][-1]["content"] == "message 13"


class TestRefusals:
    def test_own_event(self, db):
        r = post(target_id=OTHER_EVENT)
        assert r.status_code == 400 and code(r) == "cannot_report_own_event"
        assert "reports" not in db.tables

    def test_own_profile(self, db):
        r = post(target_type="user", target_id=U, origin="profile")
        assert r.status_code == 400 and code(r) == "cannot_report_own_profile"

    def test_own_profile_in_other_letter_case(self, db):
        assert post(target_type="user", target_id=U.upper(), origin="profile").status_code == 400

    def test_own_message(self, db):
        r = post(target_type="message", target_id=_msg(db, "message 2")["id"], origin="event_chat")
        assert r.status_code == 400 and code(r) == "cannot_report_own_message"

    def test_system_message(self, db):
        r = post(target_type="message", target_id=_msg(db, "Welcome")["id"], origin="event_chat")
        assert r.status_code == 400 and code(r) == "cannot_report_system_message"

    def test_message_from_a_chat_the_user_is_not_in(self, db):
        current["id"] = X
        r = post(target_type="message", target_id=_msg(db, "message 1")["id"], origin="event_chat")
        assert r.status_code == 403 and code(r) == "not_in_chat"
        assert "reports" not in db.tables

    def test_event_from_a_chat_the_user_is_not_in(self, db):
        current["id"] = X
        r = post(origin="event_chat")
        assert r.status_code == 403 and code(r) == "not_in_chat"

    def test_event_from_details_needs_no_membership(self, db):
        current["id"] = X
        assert post(origin="event_details").status_code == 201

    def test_unknown_items(self, db):
        assert code(post(target_id=UNKNOWN)) == "event_not_found"
        assert code(post(target_type="user", target_id=UNKNOWN, origin="profile")) == "user_not_found"
        r = post(target_type="message", target_id=99999, origin="event_chat")
        assert r.status_code == 404 and code(r) == "message_not_found"


class TestFailures:
    def test_administrator_account_is_refused(self, db):
        _admin_dependencies()
        current["id"] = ADMIN
        r = post()
        assert r.status_code == 403
        assert "reports" not in db.tables

    def test_regular_account_passes_the_real_onboarding_check(self, db):
        _admin_dependencies()
        assert post().status_code == 201

    def test_unexpected_insert_failure_is_a_clear_500(self, db):
        with _break(db, "reports", "insert", RuntimeError("db down")):
            r = post()
        assert r.status_code == 500 and code(r) == "report_failed"

    def test_empty_insert_response_is_a_clear_500(self, db):
        with _break(db, "reports", "insert", SimpleNamespace(data=[], count=None)):
            r = post()
        assert r.status_code == 500 and code(r) == "report_failed"

    def test_item_deleted_before_the_insert_is_a_404(self, db):
        class ForeignKeyViolation(Exception):
            code = "23503"

        with _break(db, "reports", "insert", ForeignKeyViolation()):
            r = post()
        assert r.status_code == 404 and code(r) == "item_not_found"

    @pytest.mark.parametrize("failing", ["events", "event_participants", "profiles", "event_chats"])
    def test_failed_lookup_is_not_turned_into_a_wrong_answer(self, db, failing):
        """E.g. a failed organizer lookup used to look like 'you are not in this chat' (403)."""
        current["id"] = O  # the organizer is in the chat only through the organizer lookup
        real_table = db.table

        def table(name):
            query = real_table(name)
            if name == failing:
                query.execute = lambda: (_ for _ in ()).throw(RuntimeError("db down"))
            return query

        with patch.object(db, "table", table):
            r = post(target_type="message", target_id=_msg(db, "message 1")["id"], origin="event_chat")
        assert r.status_code == 500 and code(r) == "report_failed"
        assert "reports" not in db.tables

    def test_failed_name_lookup_does_not_store_unknown_names(self, db):
        real_table = db.table

        def table(name):
            query = real_table(name)
            if name == "profiles":
                real_select = query.select

                def select(cols="*", count=None):
                    real_select(cols, count)
                    if cols == "id, username, full_name":
                        query.execute = lambda: (_ for _ in ()).throw(RuntimeError("db down"))
                    return query

                query.select = select
            return query

        with patch.object(db, "table", table):
            r = post(origin="event_chat")
        assert r.status_code == 500 and code(r) == "report_failed"
        assert "reports" not in db.tables

    def test_message_from_a_sender_without_profile_is_a_clear_404(self, db):
        ghost_message = db.add("event_chats", {"event_id": EVENT, "sender_id": GHOST, "type": "chat",
                                               "content": "boo"})
        r = post(target_type="message", target_id=ghost_message["id"], origin="event_chat")
        assert r.status_code == 404 and code(r) == "user_not_found"


class TestReasonsAndOrigin:
    @pytest.mark.parametrize("reason", ["spam", "inappropriate_content", "harassment_or_hate",
                                        "scam_or_fraud", "misleading_event"])
    def test_event_reasons(self, db, reason):
        assert post(reason=reason).status_code == 201

    def test_other_reason_with_description(self, db):
        assert post(reason="other", description="because").status_code == 201

    @pytest.mark.parametrize("reason", ["spam", "inappropriate_content", "harassment_or_hate", "scam_or_fraud"])
    def test_user_reasons(self, db, reason):
        assert post(target_type="user", target_id=V, origin="profile", reason=reason).status_code == 201

    def test_misleading_event_refused_for_user_and_message(self, db):
        assert post(target_type="user", target_id=V, origin="profile", reason="misleading_event").status_code == 422
        r = post(target_type="message", target_id=_msg(db, "message 1")["id"], origin="event_chat",
                 reason="misleading_event")
        assert r.status_code == 422

    @pytest.mark.parametrize("reason", ["", "Spam!", "bribery", None, 5, ["spam"]])
    def test_unknown_reasons_refused(self, db, reason):
        assert post(reason=reason).status_code == 422

    def test_reason_is_required(self, db):
        r = client.post("/api/reports", json={"target_type": "event", "target_id": EVENT,
                                              "origin": "event_details"}, headers=HEADERS)
        assert r.status_code == 422

    @pytest.mark.parametrize("target_type,origin", [
        ("event", "profile"), ("user", "event_details"), ("user", "event_chat"),
        ("message", "event_details"), ("message", "profile"),
    ])
    def test_origin_must_fit_the_item(self, db, target_type, origin):
        target_id = {"event": EVENT, "user": V, "message": 5}[target_type]
        assert post(target_type=target_type, target_id=target_id, origin=origin).status_code == 422

    @pytest.mark.parametrize("overrides", [
        {"target_type": "comment"}, {"target_id": "not-a-uuid"}, {"target_id": 5},
        {"target_type": "message", "origin": "event_chat", "target_id": "abc"},
        {"target_type": "message", "origin": "event_chat", "target_id": 0},
        {"target_type": "message", "origin": "event_chat", "target_id": 2 ** 70},
        {"target_type": "message", "origin": "event_chat", "target_id": True},
    ])
    def test_bad_target_refused(self, db, overrides):
        assert post(**overrides).status_code == 422


class TestDescription:
    def test_required_for_other(self, db):
        assert post(reason="other").status_code == 422
        assert post(reason="other", description="   ").status_code == 422
        assert post(reason="other", description=None).status_code == 422

    def test_optional_for_other_reasons(self, db):
        assert post(description=None).status_code == 201

    def test_max_length(self, db):
        assert post(description="a" * REPORT_DESCRIPTION_MAX_LENGTH).status_code == 201
        assert post(target_id=EVENT, reason="inappropriate_content",
                    description="a" * (REPORT_DESCRIPTION_MAX_LENGTH + 1)).status_code == 422

    def test_length_counted_after_trimming(self, db):
        assert post(description="  " + "a" * REPORT_DESCRIPTION_MAX_LENGTH + "  ").status_code == 201

    @pytest.mark.parametrize("bad", ["bad\x00text", "bell\x07", 5, ["x"], {"a": 1}])
    def test_control_characters_and_non_text_refused(self, db, bad):
        assert post(description=bad).status_code == 422

    def test_line_breaks_allowed(self, db):
        assert post(description="line one\nline two").status_code == 201


class TestAlreadyReported:
    def test_second_open_report_refused(self, db):
        assert post().status_code == 201
        r = post(reason="scam_or_fraud")
        assert r.status_code == 409 and code(r) == "already_reported"
        assert len(db.tables["reports"]) == 1

    def test_applies_to_users_and_messages(self, db):
        for kwargs in ({"target_type": "user", "target_id": V, "origin": "profile"},
                       {"target_type": "message", "target_id": _msg(db, "message 1")["id"], "origin": "event_chat"}):
            assert post(**kwargs).status_code == 201
            assert code(post(**kwargs)) == "already_reported"

    def test_event_reported_from_chat_after_details_is_still_a_duplicate(self, db):
        assert post(origin="event_details").status_code == 201
        assert code(post(origin="event_chat")) == "already_reported"

    def test_other_reporter_or_other_item_is_not_blocked(self, db):
        assert post().status_code == 201
        current["id"] = V
        assert post().status_code == 201
        current["id"] = U
        assert post(target_type="user", target_id=V, origin="profile").status_code == 201

    def test_after_closing_the_item_can_be_reported_again(self, db):
        post()
        for status in ("dismissed", "action_taken"):
            db.tables["reports"][-1]["status"] = status
            assert post().status_code == 201

    def test_unique_index_race_is_reported_as_already_reported(self, db):
        """Both requests pass the pre-check; the database's unique index stops the second insert."""
        class Violation(Exception):
            code = "23505"

        real_table = db.table

        def table(name):
            query = real_table(name)
            if name == "reports" and db.tables.get("reports"):
                query.execute = lambda: (_ for _ in ()).throw(Violation())
            return query

        with patch("app.services.report_service._has_open_report", return_value=False):
            assert post().status_code == 201
            with patch.object(db, "table", table):
                r = post(reason="scam_or_fraud")
        assert r.status_code == 409 and code(r) == "already_reported"
        assert len(db.tables["reports"]) == 1


class TestRateLimit:
    def test_over_limit_refused_with_clear_response(self, db):
        for i in range(REPORT_LIMIT):
            # Refused reports count too, so a script cannot probe without limit.
            post(target_id=OTHER_EVENT)
        r = post()
        assert r.status_code == 429
        body = r.json()
        assert body["code"] == "rate_limit_exceeded" and body["retry_after"] >= 1
        assert r.headers["Retry-After"] == str(body["retry_after"])
        assert "reports" not in db.tables

    def test_limit_is_per_user(self, db):
        for _ in range(REPORT_LIMIT + 1):
            post(target_id=OTHER_EVENT)
        current["id"] = V
        assert post().status_code == 201


class TestAuth:
    def test_requires_sign_in(self):
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_onboarded_user, None)
        r = client.post("/api/reports", json={})
        assert r.status_code in (401, 403)
