"""Ticket #236: administrators remove events and chat messages.

Routes and services run for real against the in-memory Supabase fake (tests/_fake_supabase.py).
Cast: ORG organizes EVENT, P1 and P2 joined it, OUT is not in it, ADMIN is an administrator.
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import (
    get_current_onboarded_user, get_current_user, get_optional_user, require_admin, require_regular_user,
)
from app.main import app
from tests._fake_supabase import FakeSupabase

ADMIN = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
ADMIN2 = "abababab-abab-4bab-8bab-abababababab"
ORG = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
P1 = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
P2 = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
OUT = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
EVENT = "00000000-0000-4000-8000-00000000000a"
PAST_EVENT = "00000000-0000-4000-8000-00000000000b"
CANCELLED_EVENT = "00000000-0000-4000-8000-00000000000c"
OTHER_EVENT = "00000000-0000-4000-8000-00000000000d"
UNKNOWN = "99999999-9999-4999-8999-999999999999"

SERVICE_MODULES = [
    "content_removal_service", "warning_service", "audit_service", "notification_service",
    "removed_content", "event_service", "chat_service", "admin_service", "saved_event_service",
    "participant_service", "event_search_service", "event_details_service", "recommendation_service",
    "profile_service", "invitation_service", "report_service",
]

client = TestClient(app)
HEADERS = {"Authorization": "Bearer token"}
current = {"id": ADMIN}


def _profile(uid, username, role="user"):
    return {"id": uid, "username": username, "full_name": username.title(), "role": role,
            "avatar_kind": "icon", "icon_id": None, "avatar_url": None, "visibility": "public",
            "created_at": "2026-01-01T00:00:00+00:00"}


def _event(eid, title, start, status="active", organizer=ORG):
    return {"id": eid, "title": title, "description": "d", "category": "music", "cost": 0, "max_capacity": 10,
            "status": status, "start_datetime": start, "end_datetime": start, "location_name": "Berlin",
            "latitude": 1.0, "longitude": 1.0, "created_by": organizer, "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": None, "banner_url": None, "removed_at": None, "removed_by": None}


@pytest.fixture
def db():
    fake = FakeSupabase()
    fake.tables["profiles"] = [
        _profile(ADMIN, "root", "administrator"), _profile(ADMIN2, "root2", "administrator"),
        _profile(ORG, "olga"), _profile(P1, "pia"), _profile(P2, "pat"), _profile(OUT, "otto"),
    ]
    fake.tables["events"] = [
        _event(EVENT, "Sunset Picnic", "2099-01-01T10:00:00+00:00"),
        _event(PAST_EVENT, "Old Party", "2020-01-01T10:00:00+00:00"),
        _event(CANCELLED_EVENT, "Cancelled Fest", "2099-02-01T10:00:00+00:00", status="cancelled"),
        _event(OTHER_EVENT, "Other Event", "2099-03-01T10:00:00+00:00"),
    ]
    fake.tables["event_participants"] = [
        {"user_id": u, "event_id": e, "status": "going"}
        for e in (EVENT, PAST_EVENT, CANCELLED_EVENT) for u in (ORG, P1, P2)
    ]
    fake.tables["warnings"], fake.tables["notifications"], fake.tables["logs"] = [], [], []
    fake.add("event_chats", {"event_id": EVENT, "sender_id": None, "type": "notification", "content": "Welcome"})
    fake.add("event_chats", {"event_id": EVENT, "sender_id": P1, "type": "chat", "content": "hello all"})
    fake.add("event_chats", {"event_id": EVENT, "sender_id": P2, "type": "chat",
                             "content": "you are all\nidiots " + "x" * 200})
    fake.add("event_chats", {"event_id": OTHER_EVENT, "sender_id": P1, "type": "chat", "content": "elsewhere"})
    patches = [patch(f"app.services.{m}.supabase", fake) for m in SERVICE_MODULES]
    patches += [patch("app.core.dependencies.supabase", fake)]
    for p in patches:
        p.start()
    who = lambda: SimpleNamespace(id=current["id"], email="x@y.z")
    app.dependency_overrides[require_admin] = who
    app.dependency_overrides[get_current_user] = who
    app.dependency_overrides[get_current_onboarded_user] = who
    app.dependency_overrides[get_optional_user] = who
    current["id"] = ADMIN
    yield fake
    for p in patches:
        p.stop()
    for dep in (require_admin, get_current_user, get_current_onboarded_user, get_optional_user):
        app.dependency_overrides.pop(dep, None)


def msg(db, content_start):
    return next(m for m in db.tables["event_chats"] if (m["content"] or "").startswith(content_start))


def remove_event(event_id=EVENT, **body):
    return client.post(f"/api/admin/events/{event_id}/remove", json=body or None, headers=HEADERS)


def remove_message(message_id, event_id=EVENT, **body):
    return client.post(f"/api/admin/events/{event_id}/messages/{message_id}/remove",
                       json=body or None, headers=HEADERS)


def code(response):
    return response.json()["detail"]["code"]


def notes(db, user, type_=None):
    return [n for n in db.tables["notifications"]
            if n["user_id"] == user and (type_ is None or n["type"] == type_)]


class TestRemoveEvent:
    def test_marks_the_event_and_deletes_nothing(self, db):
        r = remove_event()
        assert r.status_code == 200
        body = r.json()
        assert body["is_removed"] is True and body["removed_at"] and body["removed_by"]["id"] == ADMIN
        row = next(e for e in db.tables["events"] if e["id"] == EVENT)
        assert row["removed_at"] and row["removed_by"] == ADMIN
        assert len(db.tables["events"]) == 4 and len(db.tables["event_participants"]) == 9
        assert len([m for m in db.tables["event_chats"] if m["event_id"] == EVENT]) == 3

    def test_removing_twice_is_refused(self, db):
        assert remove_event().status_code == 200
        r = remove_event()
        assert r.status_code == 409 and code(r) == "already_removed"
        assert len(db.tables["warnings"]) == 1  # the second request gave no second warning

    def test_two_administrators_at_once_only_one_wins(self, db):
        """The mark is made conditional on removed_at being null, so a lost race is a 409."""
        real_table = db.table

        def table(name):
            query = real_table(name)
            if name == "events":
                real_update = query.update

                def update(payload):
                    for e in db.tables["events"]:  # the other administrator got there first
                        if e["id"] == EVENT:
                            e["removed_at"], e["removed_by"] = "2026-10-26T00:00:00+00:00", ADMIN2
                    return real_update(payload)

                query.update = update
            return query

        with patch.object(db, "table", table):
            r = remove_event()
        assert r.status_code == 409 and code(r) == "already_removed"
        assert db.tables["warnings"] == [] and db.tables["notifications"] == []

    def test_unknown_or_malformed_event(self, db):
        assert code(remove_event(UNKNOWN)) == "event_not_found"
        r = remove_event("not-a-uuid")
        assert r.status_code == 404 and code(r) == "event_not_found"

    def test_user_account_is_refused(self, db):
        """A signed-in user (not an administrator) cannot remove an event, even by a direct request."""
        app.dependency_overrides.pop(require_admin, None)
        current["id"] = P1
        r = remove_event()
        assert r.status_code == 403
        assert next(e for e in db.tables["events"] if e["id"] == EVENT)["removed_at"] is None
        assert db.tables["warnings"] == [] and db.tables["logs"] == []

    def test_user_account_is_refused_for_messages_too(self, db):
        app.dependency_overrides.pop(require_admin, None)
        current["id"] = P1
        r = remove_message(msg(db, "you are all")["id"])
        assert r.status_code == 403 and msg(db, "you are all").get("removed_at") is None

    def test_body_with_unknown_fields_is_refused(self, db):
        assert remove_event(reason="because").status_code == 422
        assert remove_event(report_id=0).status_code == 422


class TestWarningAndNotifications:
    def test_organizer_gets_a_warning_that_says_what_was_removed(self, db):
        body = remove_event().json()
        [warning] = db.tables["warnings"]
        assert body["warning_id"] == warning["id"]
        assert warning["user_id"] == ORG and warning["admin_id"] == ADMIN
        assert "Sunset Picnic" in warning["reason"] and "removed by an administrator" in warning["reason"]
        assert (warning["about_type"], warning["about_id"]) == ("event", EVENT)
        assert warning.get("withdrawn_at") is None and warning.get("acknowledged_at") is None

    def test_warning_counts_appears_in_history_and_waits_for_acknowledgement(self, db):
        remove_event()
        history = client.get(f"/api/admin/users/{ORG}/warnings", headers=HEADERS).json()
        assert [i["about"] for i in history["items"]] == [{"type": "event", "id": EVENT}]
        app.dependency_overrides[require_regular_user] = lambda: SimpleNamespace(id=ORG, email="x@y.z")
        try:
            pending = client.get("/api/warnings/pending", headers=HEADERS)
            assert pending.status_code == 200 and len(pending.json()["items"]) == 1
            warning_id = pending.json()["items"][0]["id"]
            ack = client.post(f"/api/warnings/{warning_id}/acknowledge", headers=HEADERS)
            assert ack.status_code == 200
            assert client.get("/api/warnings/pending", headers=HEADERS).json()["items"] == []
        finally:
            app.dependency_overrides.pop(require_regular_user, None)

    def test_owner_gets_exactly_one_notification_and_no_warning_notification(self, db):
        remove_event()
        [note] = notes(db, ORG)
        assert note["type"] == "content_removed" and note["event_id"] == EVENT
        assert "Your content was removed" in note["message"] and "Sunset Picnic" in note["message"]
        assert "counts as a warning" in note["message"]
        assert note["warning_id"] == db.tables["warnings"][0]["id"]
        assert notes(db, ORG, "warning") == []

    def test_notification_list_links_the_warning(self, db):
        remove_event()
        current["id"] = ORG
        [row] = client.get("/api/notifications/all", headers=HEADERS).json()["data"]
        assert row["type"] == "content_removed" and row["is_warning"] is False
        assert row["warning_id"] and row["warning_acknowledged"] is False and row["warning_withdrawn"] is False

    def test_owner_who_is_now_an_administrator_gets_no_warning(self, db):
        next(p for p in db.tables["profiles"] if p["id"] == ORG)["role"] = "administrator"
        body = remove_event().json()
        assert body["is_removed"] is True and body["warning_id"] is None
        assert db.tables["warnings"] == []
        [note] = notes(db, ORG)
        assert note["warning_id"] is None and "counts as a warning" not in note["message"]

    def test_failed_warning_undoes_the_removal_so_it_can_be_retried(self, db):
        with patch("app.services.content_removal_service.give_removal_warning", side_effect=RuntimeError("db")):
            r = remove_event()
        assert r.status_code == 500 and code(r) == "removal_failed"
        assert next(e for e in db.tables["events"] if e["id"] == EVENT)["removed_at"] is None
        assert db.tables["notifications"] == [] and db.tables["logs"] == []
        assert remove_event().status_code == 200

    def test_failed_notifications_do_not_fail_the_removal(self, db):
        real_table = db.table

        def table(name):
            query = real_table(name)
            if name == "notifications":
                query.execute = lambda: (_ for _ in ()).throw(RuntimeError("db down"))
            return query

        with patch.object(db, "table", table):
            r = remove_event()
        assert r.status_code == 200 and r.json()["warning_id"]
        assert db.tables["warnings"] and next(e for e in db.tables["events"] if e["id"] == EVENT)["removed_at"]
        assert db.tables["logs"][0]["type"] == "event_removed"  # still audited


class TestParticipantsNotified:
    def test_participants_of_an_upcoming_event_are_notified_without_the_reason(self, db):
        r = remove_event()
        assert r.status_code == 200
        for user in (P1, P2):
            [note] = notes(db, user)
            assert note["type"] == "event_removed" and note["event_id"] == EVENT
            assert note["message"] == 'Event "Sunset Picnic" was removed by an administrator.'
            assert "warning" not in note["message"].lower()
        assert notes(db, OUT) == []
        assert [n["type"] for n in notes(db, ORG)] == ["content_removed"]  # the organizer gets only this

    def test_past_event_notifies_nobody_but_the_organizer(self, db):
        remove_event(PAST_EVENT)
        assert notes(db, P1) == [] and notes(db, P2) == []
        assert len(notes(db, ORG)) == 1

    def test_cancelled_event_notifies_nobody_but_the_organizer(self, db):
        remove_event(CANCELLED_EVENT)
        assert notes(db, P1) == [] and len(notes(db, ORG)) == 1


class TestAuditLog:
    def test_removal_is_recorded(self, db):
        remove_event()
        [entry] = db.tables["logs"]
        assert entry["type"] == "event_removed" and entry["created_by_id"] == ADMIN
        assert entry["entity_type"] == "event" and entry["entity_id"] == EVENT
        assert "report_id:none" in entry["values"]

    def test_removal_from_a_report_records_the_report(self, db):
        db.add("reports", {"reporter_id": P1, "target_type": "event", "event_id": EVENT, "reason": "spam",
                           "origin": "event_details", "status": "open"})
        report_id = db.tables["reports"][0]["id"]
        r = remove_event(report_id=report_id)
        assert r.status_code == 200 and r.json()["report_id"] == report_id
        assert f"report_id:{report_id}" in db.tables["logs"][0]["values"]
        assert str(report_id) in db.tables["logs"][0]["description"]

    def test_audit_log_endpoint_lists_it(self, db):
        remove_event()
        items = client.get("/api/admin/audit-log", headers=HEADERS).json()["items"]
        assert items[0]["action"] == "event_removed" and items[0]["target"]["type"] == "event"

    def test_report_must_be_about_this_event(self, db):
        db.add("reports", {"reporter_id": P1, "target_type": "event", "event_id": OTHER_EVENT, "reason": "spam",
                           "origin": "event_details", "status": "open"})
        db.add("reports", {"reporter_id": P1, "target_type": "message", "event_id": EVENT,
                           "message_id": msg(db, "hello")["id"], "reason": "spam",
                           "origin": "event_chat", "status": "open"})
        for report in db.tables["reports"]:
            r = remove_event(report_id=report["id"])
            assert r.status_code == 400 and code(r) == "report_mismatch"
        assert remove_event(report_id=99999).status_code == 404
        assert next(e for e in db.tables["events"] if e["id"] == EVENT)["removed_at"] is None


class TestRemoveMessage:
    def test_marks_message_and_deletes_nothing(self, db):
        target = msg(db, "you are all")
        r = remove_message(target["id"])
        assert r.status_code == 200
        body = r.json()
        assert body["message_id"] == target["id"] and body["is_removed"] and body["removed_by"]["id"] == ADMIN
        assert target["removed_at"] and target["removed_by"] == ADMIN
        assert target["content"].startswith("you are all")  # still stored
        assert len(db.tables["event_chats"]) == 4

    def test_twice_is_refused(self, db):
        target = msg(db, "you are all")
        assert remove_message(target["id"]).status_code == 200
        r = remove_message(target["id"])
        assert r.status_code == 409 and code(r) == "already_removed"
        assert len(db.tables["warnings"]) == 1

    def test_system_message_is_refused(self, db):
        r = remove_message(msg(db, "Welcome")["id"])
        assert r.status_code == 400 and code(r) == "cannot_remove_system_message"

    def test_unknown_message_or_message_of_another_event(self, db):
        assert code(remove_message(99999)) == "message_not_found"
        r = remove_message(msg(db, "elsewhere")["id"])  # that message is in OTHER_EVENT's chat
        assert r.status_code == 404 and code(r) == "message_not_found"
        assert remove_message(1, event_id="not-a-uuid").status_code == 404

    def test_sender_gets_a_warning_and_one_notification(self, db):
        target = msg(db, "you are all")
        remove_message(target["id"])
        [warning] = db.tables["warnings"]
        assert warning["user_id"] == P2 and (warning["about_type"], warning["about_id"]) == (
            "chat_message", str(target["id"]))
        assert "Sunset Picnic" in warning["reason"] and "you are all idiots" in warning["reason"]
        assert len(warning["reason"]) < 400  # the quoted text is cut short
        [note] = notes(db, P2)
        assert note["type"] == "content_removed" and note["event_id"] == EVENT
        assert "Your content was removed" in note["message"] and "Sunset Picnic" in note["message"]
        assert "counts as a warning" in note["message"] and note["warning_id"] == warning["id"]
        assert notes(db, P2, "warning") == [] and notes(db, P1) == []  # nobody else is told

    def test_sender_who_is_now_an_administrator_gets_no_warning(self, db):
        next(p for p in db.tables["profiles"] if p["id"] == P2)["role"] = "administrator"
        r = remove_message(msg(db, "you are all")["id"])
        assert r.status_code == 200 and r.json()["warning_id"] is None and db.tables["warnings"] == []

    def test_audit_with_report(self, db):
        target = msg(db, "you are all")
        db.add("reports", {"reporter_id": P1, "target_type": "message", "event_id": EVENT,
                           "message_id": target["id"], "reason": "spam", "origin": "event_chat", "status": "open"})
        report_id = db.tables["reports"][0]["id"]
        assert remove_message(target["id"], report_id=report_id).status_code == 200
        [entry] = db.tables["logs"]
        assert entry["type"] == "message_removed" and entry["entity_type"] == "chat_message"
        assert entry["entity_id"] == str(target["id"]) and f"report_id:{report_id}" in entry["values"]

    def test_report_about_another_message_is_a_mismatch(self, db):
        db.add("reports", {"reporter_id": P1, "target_type": "message", "event_id": EVENT,
                           "message_id": msg(db, "hello")["id"], "reason": "spam",
                           "origin": "event_chat", "status": "open"})
        r = remove_message(msg(db, "you are all")["id"], report_id=db.tables["reports"][0]["id"])
        assert r.status_code == 400 and code(r) == "report_mismatch"

    def test_failed_warning_undoes_the_removal(self, db):
        target = msg(db, "you are all")
        with patch("app.services.content_removal_service.give_removal_warning", side_effect=RuntimeError("db")):
            r = remove_message(target["id"])
        assert r.status_code == 500 and code(r) == "removal_failed"
        assert target["removed_at"] is None


class TestUsersNoLongerSeeRemovedEvents:
    @pytest.fixture(autouse=True)
    def _remove(self, db):
        db.tables["saved_events"] = [{"user_id": P1, "event_id": EVENT}, {"user_id": P1, "event_id": OTHER_EVENT}]
        remove_event()
        current["id"] = P1

    def test_event_list_for_home_page_and_map(self, db):
        from app.services.event_service import list_events
        ids = [e["id"] for e in list_events()["data"]]
        assert EVENT not in ids and OTHER_EVENT in ids

    def test_event_list_search_path(self, db):
        from app.services.event_service import list_events
        rows = [dict(e) for e in db.tables["events"]]
        for row in rows:
            row["end_datetime"] = "2099-12-31T00:00:00+00:00"
            row.pop("removed_at")  # RPC rows do not carry it
        db.rpc_results["search_events"] = rows
        with patch("app.services.event_service.generate_embedding", return_value=[0.1]):
            ids = [e["id"] for e in list_events(search="picnic")["data"]]
        assert EVENT not in ids and OTHER_EVENT in ids

    def test_assistant_style_search(self, db):
        from app.services.event_search_service import search_events
        for event in db.tables["events"]:
            event["end_datetime"] = "2099-12-31T00:00:00+00:00"
        result = search_events({}, viewer_id=P1)
        assert result["success"] is True
        assert [e["id"] for e in result["events"]] == [OTHER_EVENT]

    def test_recommendations(self, db):
        from app.services.recommendation_service import get_recommendations
        rows = [{**e, "end_datetime": "2099-12-31T00:00:00+00:00"} for e in db.tables["events"]
                if e["id"] != OTHER_EVENT]
        for row in rows:
            row.pop("removed_at")
        db.rpc_results["search_events"] = rows
        db.tables["profiles"][3]["interest_embedding"] = [0.1, 0.2]
        db.tables["event_participants"] = []
        with patch("app.services.recommendation_service.generate_embedding", return_value=[0.1, 0.2]):
            data = get_recommendations(P1)["data"]
        assert EVENT not in [e["id"] for e in data]

    def test_profiles_organized_and_joined(self, db):
        from app.services.event_service import get_profile_events
        for user in (ORG, P2):
            result = get_profile_events(user, viewer_id=P1)
            ids = [e["id"] for group in result.values() for part in group.values() for e in part]
            assert EVENT not in ids

    def test_favourites(self, db):
        from app.services.saved_event_service import get_saved_events
        assert [e["id"] for e in get_saved_events(P1)] == [OTHER_EVENT]

    def test_my_events_lists(self, db):
        current["id"] = ORG
        ids = [e["id"] for e in client.get("/api/events/my-events", headers=HEADERS).json()["data"]]
        assert EVENT not in ids
        mine = client.get("/api/participants/my/events", headers=HEADERS).json()
        assert {row["event_id"] for row in mine} == {PAST_EVENT, CANCELLED_EVENT}

    def test_opening_a_removed_event_says_it_was_removed(self, db):
        r = client.get(f"/api/events/{EVENT}", headers=HEADERS)
        assert r.status_code == 410
        assert r.json()["detail"] == {"code": "event_removed",
                                      "message": "This event was removed by an administrator."}
        assert client.get(f"/api/events/{OTHER_EVENT}", headers=HEADERS).status_code == 200

    def test_anonymous_visitors_get_the_same_answer(self, db):
        app.dependency_overrides[get_optional_user] = lambda: None
        assert client.get(f"/api/events/{EVENT}").status_code == 410

    def test_joining_editing_and_cancelling_are_refused(self, db):
        current["id"] = OUT
        assert client.post(f"/api/participants/{EVENT}/join", headers=HEADERS).status_code == 410
        current["id"] = ORG
        assert client.patch(f"/api/events/{EVENT}/cancel", headers=HEADERS).status_code == 410

    # Invitations to a removed event are covered in test_content_removal_review_fixes.py.


class TestChatOfRemovedEvent:
    def test_chat_returns_that_the_event_was_removed(self, db):
        remove_event()
        current["id"] = P1
        r = client.get(f"/api/chats/{EVENT}/messages", headers=HEADERS)
        assert r.status_code == 410 and code(r) == "event_removed"

    def test_no_new_messages_are_accepted(self, db):
        remove_event()
        current["id"] = P1
        before = len(db.tables["event_chats"])
        r = client.post(f"/api/chats/{EVENT}/messages", json={"content": "anyone?"}, headers=HEADERS)
        assert r.status_code == 410 and code(r) == "event_removed"
        assert len(db.tables["event_chats"]) == before

    def test_editing_and_deleting_in_it_are_refused(self, db):
        remove_event()
        current["id"] = P1
        mine = msg(db, "hello")
        assert client.put(f"/api/chats/messages/{mine['id']}", json={"content": "x"}, headers=HEADERS).status_code == 410
        assert client.delete(f"/api/chats/messages/{mine['id']}", headers=HEADERS).status_code == 410

    def test_other_chats_are_not_affected(self, db):
        remove_event()
        db.tables["event_participants"].append({"user_id": P1, "event_id": OTHER_EVENT, "status": "going"})
        current["id"] = P1
        assert client.get(f"/api/chats/{OTHER_EVENT}/messages", headers=HEADERS).status_code == 200


class TestRemovedMessageInChat:
    def test_everyone_in_the_chat_gets_it_as_removed_without_text(self, db):
        target = msg(db, "you are all")
        remove_message(target["id"])
        for viewer in (P1, P2, ORG):  # a participant, the sender and the organizer
            current["id"] = viewer
            data = client.get(f"/api/chats/{EVENT}/messages", headers=HEADERS).json()["data"]
            removed = next(m for m in data if m["id"] == target["id"])
            assert removed["is_removed"] is True and removed["removed_at"] and removed["content"] == ""
            assert "idiots" not in str(removed) and "removed_by" not in removed
            assert removed["sender_id"] == P2 and removed["sender"]["id"] == P2
            normal = next(m for m in data if m["content"] == "hello all")
            assert normal["is_removed"] is False and normal["removed_at"] is None

    def test_removed_message_cannot_be_edited_or_deleted_even_by_its_sender(self, db):
        target = msg(db, "you are all")
        remove_message(target["id"])
        current["id"] = P2
        r = client.put(f"/api/chats/messages/{target['id']}", json={"content": "sorry"}, headers=HEADERS)
        assert r.status_code == 400 and code(r) == "message_removed"
        r = client.delete(f"/api/chats/messages/{target['id']}", headers=HEADERS)
        assert r.status_code == 400 and code(r) == "message_removed"
        assert target["content"].startswith("you are all") and target in db.tables["event_chats"]


class TestAdminPanelShowsRemovedState:
    def test_event_list_and_details_say_it_is_removed_and_when(self, db):
        removed_at = remove_event().json()["removed_at"]
        items = client.get("/api/admin/events", headers=HEADERS).json()["items"]
        by_id = {i["id"]: i for i in items}
        assert by_id[EVENT]["is_removed"] is True and by_id[EVENT]["removed_at"] == removed_at
        assert by_id[EVENT]["removed_by"]["id"] == ADMIN
        assert by_id[OTHER_EVENT]["is_removed"] is False and by_id[OTHER_EVENT]["removed_at"] is None
        detail = client.get(f"/api/admin/events/{EVENT}", headers=HEADERS).json()
        assert detail["is_removed"] is True and detail["removed_at"] == removed_at
        assert detail["removed_by"]["id"] == ADMIN and detail["removed_by"]["username"] == "root"
        assert detail["status"] == "active"  # removal is separate from cancellation

    def test_removed_events_stay_in_the_lists_and_user_details(self, db):
        remove_event()
        listed = [i["id"] for i in client.get("/api/admin/events?status_filter=upcoming", headers=HEADERS).json()["items"]]
        assert EVENT in listed
        user = client.get(f"/api/admin/users/{ORG}", headers=HEADERS).json()
        card = next(e for e in user["organized_events"]["upcoming"] if e["id"] == EVENT)
        assert card["is_removed"] is True and card["removed_at"]

    def test_chat_view_marks_removed_messages_and_keeps_their_text(self, db):
        target = msg(db, "you are all")
        remove_message(target["id"])
        detail = client.get(f"/api/admin/events/{EVENT}", headers=HEADERS).json()
        removed = next(c for c in detail["chats"] if c["id"] == target["id"])
        assert removed["is_removed"] is True and removed["removed_at"] and removed["removed_by"]["id"] == ADMIN
        assert removed["text"].startswith("you are all")
        normal = next(c for c in detail["chats"] if c["text"] == "hello all")
        assert normal["is_removed"] is False and normal["removed_by"] is None
        assert detail["chat"] == detail["chats"]

    def test_existing_fields_are_still_there(self, db):
        detail = client.get(f"/api/admin/events/{EVENT}", headers=HEADERS).json()
        for field in ("id", "title", "status", "is_cancelled", "organizer", "participants", "chats", "chat", "banner"):
            assert field in detail
        assert detail["is_removed"] is False and detail["removed_by"] is None
