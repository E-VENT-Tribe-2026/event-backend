"""Ticket #235 phase 4: report history in a user's details and closed-reports count on the account screen
(test first).

  GET /api/admin/users/{id}   -> new field `report_history` {"about": [...], "made": [...]} (null for an administrator)
  GET /api/admin/account      -> new field `reports_closed` (int)

Driven through HTTP against the real app and the in-memory Supabase fake (tests/_fake_supabase.py), with the
same patching approach as tests/test_admin_reports_read.py. The tests assert responses. They deliberately also
pin a few lookup rules the responses cannot show: the event-report lookups use id lists of at most LOOKUP_CHUNK
(and none at all for an organizer without events), every list is read completely even when the server caps a
response below the data size (capped-fake tests), and the closed-reports count asks for at most one row.

Refusal of non-admin accounts on both endpoints is already covered by
tests/test_admin_panel.py::test_admin_endpoints_refuse_non_admin (user-role aal2 -> 403 on
GET /api/admin/users/some-id and GET /api/admin/account), and the shared require_admin chain is covered for
administrator aal1 by tests/test_admin_reports_read.py, so nothing is added here for refusals.
"""
import importlib
import pkgutil
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import app.services as services_pkg
from app.core.dependencies import require_admin
from app.main import app
from app.services.removed_content import LOOKUP_CHUNK
from tests import _fake_supabase
from tests._fake_supabase import FakeSupabase

ADM = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"    # the signed-in administrator
ADM2 = "abababab-abab-4bab-8bab-abababababab"   # another administrator
MIA = "11111111-1111-4111-8111-111111111111"
TOM = "22222222-2222-4222-8222-222222222222"   # the user whose details are read; organizes EV_TOM and EV_TOM2
ANA = "33333333-3333-4333-8333-333333333333"
EV_TOM = "550e8400-e29b-41d4-a716-446655440000"
EV_TOM2 = "9b2f3c1e-6a47-4c0e-8d55-0f1a2b3c4d5e"
EV_ANA = "0f1a2b3c-4d5e-4f60-8a71-92b3c4d5e6f7"   # organized by someone else
EV_ADM2 = "7c1d2e3f-4a5b-4c6d-8e7f-8091a2b3c4d5"  # organized by an administrator

client = TestClient(app)
SKIP_MODULES = {"block_visibility", "removed_content"}  # conftest patches these itself

BASE_KEYS = {"id", "status", "created_at", "target_type", "reason"}


def _profile(uid, username, role="user", **extra):
    row = {"id": uid, "username": username, "full_name": username.title(), "role": role,
           "avatar_url": f"https://img/{username}.png", "avatar_kind": "photo", "icon_id": None,
           "visibility": "public", "created_at": "2026-01-01T00:00:00+00:00", "suspended_at": None}
    row.update(extra)
    return row


def _event(eid, title, created_by):
    return {"id": eid, "title": title, "created_by": created_by, "banner_url": f"https://img/{title}.jpg",
            "status": "active", "start_datetime": "2027-01-01T00:00:00+00:00",
            "end_datetime": "2027-01-01T02:00:00+00:00", "removed_at": None, "removed_by": None}


def _report(rid, created_at, **kw):
    row = {"id": rid, "reporter_id": MIA, "target_type": "event", "event_id": EV_TOM, "reported_user_id": None,
           "message_id": None, "reason": "spam", "description": None, "origin": "event_details",
           "status": "open", "chat_context": None, "created_at": created_at,
           "outcome": None, "closed_by": None, "closed_at": None}
    row.update(kw)
    return row


def _user_report(rid, created_at, about=TOM, **kw):
    return _report(rid, created_at, target_type="user", event_id=None, reported_user_id=about,
                   origin="profile", **kw)


def _msg_report(rid, created_at, about=TOM, message_id=42, event_id=EV_TOM, **kw):
    return _report(rid, created_at, target_type="message", event_id=event_id, reported_user_id=about,
                   message_id=message_id, origin="event_chat", chat_context=[], **kw)


def _closed(by=ADM, status="dismissed", outcome="dismissed"):
    return {"status": status, "outcome": outcome, "closed_by": by, "closed_at": "2026-10-09T00:00:00+00:00"}


def _modules_with_supabase():
    mods = [importlib.import_module("app.api.v1.admin_routes")]
    for info in pkgutil.iter_modules(services_pkg.__path__):
        if info.name in SKIP_MODULES:
            continue
        mods.append(importlib.import_module(f"app.services.{info.name}"))
    return [m for m in mods if hasattr(m, "supabase")]


@pytest.fixture
def db():
    fake = FakeSupabase()
    fake.tables["profiles"] = [
        _profile(ADM, "boss", "administrator", admin_since="2026-03-01T12:00:00+00:00"),
        _profile(ADM2, "boss2", "administrator", admin_since="2026-04-01T12:00:00+00:00"),
        _profile(MIA, "mia"), _profile(TOM, "tom"), _profile(ANA, "ana"),
    ]
    fake.tables["events"] = [_event(EV_TOM, "Board game night", TOM), _event(EV_TOM2, "Sunset party", TOM),
                             _event(EV_ANA, "Ana's picnic", ANA), _event(EV_ADM2, "Admin meetup", ADM2)]
    for name in ("event_chats", "reports", "event_participants", "user_blocks", "friendships", "warnings"):
        fake.tables[name] = []
    patches = [patch.object(m, "supabase", fake) for m in _modules_with_supabase()]
    for p in patches:
        p.start()
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id=ADM)
    yield fake
    for p in patches:
        p.stop()
    app.dependency_overrides.clear()


def _put(db, *rows):
    db.tables["reports"].extend(rows)


def _ids(items):
    return [i["id"] for i in items]


def _user(uid=TOM):
    res = client.get(f"/api/admin/users/{uid}")
    assert res.status_code == 200, res.text
    return res.json()


def _history(uid=TOM):
    body = _user(uid)
    assert "report_history" in body, f"report_history missing from the response, keys: {sorted(body)}"
    return body["report_history"]


def _account():
    res = client.get("/api/admin/account")
    assert res.status_code == 200, res.text
    return res.json()


# ---- GET /api/admin/users/{id}: shape and empty ------------------------------------

def test_history_is_empty_lists_not_null_for_user_without_reports(db):
    hist = _history()
    assert hist == {"about": [], "made": []}


def test_history_has_exactly_about_and_made(db):
    _put(db, _user_report(1, "2026-10-01T10:00:00+00:00"))
    hist = _history()
    assert isinstance(hist, dict) and set(hist) == {"about", "made"}


# ---- about ---------------------------------------------------------------------------

def test_about_user_report_entry_shape(db):
    _put(db, _user_report(1, "2026-10-01T10:00:00+00:00", reason="harassment_or_hate"))
    about = _history()["about"]
    assert len(about) == 1
    entry = about[0]
    assert set(entry) == BASE_KEYS | {"event"}
    assert entry["id"] == 1 and entry["status"] == "open" and entry["target_type"] == "user"
    assert entry["reason"] == "harassment_or_hate"
    assert entry["created_at"] == "2026-10-01T10:00:00+00:00"
    assert entry["event"] is None


def test_about_message_report_about_the_users_own_message(db):
    db.tables["event_chats"].append({"id": 42, "event_id": EV_ANA, "sender_id": TOM, "content": "rude",
                                     "type": "chat", "removed_at": None, "removed_by": None,
                                     "created_at": "2026-10-28T18:00:42+00:00"})
    _put(db, _msg_report(1, "2026-10-01T10:00:00+00:00", event_id=EV_ANA, reason="harassment_or_hate"))
    about = _history()["about"]
    assert _ids(about) == [1]
    assert about[0]["target_type"] == "message" and about[0]["event"] is None
    assert about[0]["reason"] == "harassment_or_hate"


def test_about_message_report_in_own_event_about_own_message_has_no_event_marker(db):
    _put(db, _msg_report(1, "2026-10-01T10:00:00+00:00", event_id=EV_TOM))
    about = _history()["about"]
    assert _ids(about) == [1]
    assert about[0]["event"] is None  # only event reports carry the event


def test_about_event_report_about_an_event_the_user_organizes_is_marked_with_the_event(db):
    _put(db, _report(1, "2026-10-01T10:00:00+00:00", event_id=EV_TOM, reason="misleading_event",
                     status="action_taken", outcome="warned", closed_by=ADM,
                     closed_at="2026-10-02T00:00:00+00:00"))
    about = _history()["about"]
    assert _ids(about) == [1]
    entry = about[0]
    assert entry["target_type"] == "event" and entry["status"] == "action_taken"
    assert entry["reason"] == "misleading_event"
    assert entry["event"]["id"] == EV_TOM and entry["event"]["title"] == "Board game night"
    assert set(entry) == BASE_KEYS | {"event"}
    assert set(entry["event"]) == {"id", "title"}


def test_about_has_all_three_kinds_together_and_marks_only_the_event_report(db):
    _put(db,
         _user_report(1, "2026-10-01T10:00:00+00:00"),
         _msg_report(2, "2026-10-02T10:00:00+00:00", event_id=EV_ANA),
         _report(3, "2026-10-03T10:00:00+00:00", event_id=EV_TOM))
    about = _history()["about"]
    assert _ids(about) == [3, 2, 1]
    by_id = {i["id"]: i for i in about}
    assert by_id[3]["target_type"] == "event" and by_id[3]["event"]["id"] == EV_TOM
    assert by_id[3]["event"]["title"] == "Board game night"
    assert by_id[2]["target_type"] == "message" and by_id[2]["event"] is None
    assert by_id[1]["target_type"] == "user" and by_id[1]["event"] is None


def test_about_excludes_message_report_about_someone_elses_message_in_the_users_event_chat(db):
    _put(db,
         _msg_report(1, "2026-10-01T10:00:00+00:00", about=ANA, event_id=EV_TOM),
         _user_report(2, "2026-10-02T10:00:00+00:00"))
    assert _ids(_history()["about"]) == [2]


def test_about_excludes_event_report_about_another_organizers_event(db):
    _put(db,
         _report(1, "2026-10-01T10:00:00+00:00", event_id=EV_ANA),
         _report(2, "2026-10-02T10:00:00+00:00", event_id=EV_ADM2),
         _report(3, "2026-10-03T10:00:00+00:00", event_id=EV_TOM))
    assert _ids(_history()["about"]) == [3]


def test_about_excludes_event_report_with_deleted_event(db):
    _put(db,
         _report(1, "2026-10-01T10:00:00+00:00", event_id=None),
         _report(2, "2026-10-02T10:00:00+00:00", event_id=None, reporter_id=TOM))
    hist = _history()
    assert hist["about"] == []
    assert _ids(hist["made"]) == [2]  # still a report TOM made


def test_about_excludes_reports_about_other_users(db):
    _put(db, _user_report(1, "2026-10-01T10:00:00+00:00", about=ANA),
         _msg_report(2, "2026-10-02T10:00:00+00:00", about=ANA, event_id=EV_ANA))
    hist = _history()
    assert hist == {"about": [], "made": []}


def test_user_organizing_an_event_with_several_reports_about_it(db):
    _put(db,
         _report(1, "2026-10-01T10:00:00+00:00", event_id=EV_TOM, reporter_id=MIA, reason="spam"),
         _report(2, "2026-10-02T10:00:00+00:00", event_id=EV_TOM, reporter_id=ANA, reason="scam_or_fraud",
                 **_closed()),
         _report(3, "2026-10-03T10:00:00+00:00", event_id=EV_TOM, reporter_id=ADM2, reason="other",
                 **_closed(status="action_taken", outcome="content_removed")),
         _report(4, "2026-10-04T10:00:00+00:00", event_id=EV_TOM2, reporter_id=MIA))
    about = _history()["about"]
    assert _ids(about) == [4, 3, 2, 1]
    assert [i["status"] for i in about] == ["open", "action_taken", "dismissed", "open"]
    assert [i["event"]["id"] for i in about] == [EV_TOM2, EV_TOM, EV_TOM, EV_TOM]
    assert [i["event"]["title"] for i in about] == ["Sunset party", "Board game night",
                                                      "Board game night", "Board game night"]
    assert [i["reason"] for i in about] == ["spam", "other", "scam_or_fraud", "spam"]


def test_about_includes_every_status(db):
    _put(db,
         _user_report(1, "2026-10-01T10:00:00+00:00"),
         _user_report(2, "2026-10-02T10:00:00+00:00", **_closed()),
         _user_report(3, "2026-10-03T10:00:00+00:00", **_closed(status="action_taken", outcome="warned")))
    about = _history()["about"]
    assert [i["status"] for i in about] == ["action_taken", "dismissed", "open"]


# ---- made ----------------------------------------------------------------------------

def test_made_lists_reports_filed_by_the_user_any_status_any_target(db):
    db.tables["event_chats"].append({"id": 42, "event_id": EV_ANA, "sender_id": ANA, "content": "x",
                                     "type": "chat", "removed_at": None, "removed_by": None,
                                     "created_at": "2026-10-28T18:00:42+00:00"})
    _put(db,
         _report(1, "2026-10-01T10:00:00+00:00", reporter_id=TOM, event_id=EV_ANA, reason="spam"),
         _user_report(2, "2026-10-02T10:00:00+00:00", reporter_id=TOM, about=ANA, reason="other",
                      **_closed()),
         _msg_report(3, "2026-10-03T10:00:00+00:00", reporter_id=TOM, about=ANA, event_id=EV_ANA,
                     reason="harassment_or_hate", **_closed(status="action_taken", outcome="warned")),
         _report(4, "2026-10-04T10:00:00+00:00", reporter_id=MIA, event_id=EV_ANA))  # filed by someone else
    hist = _history()
    made = hist["made"]
    assert _ids(made) == [3, 2, 1]
    assert [i["target_type"] for i in made] == ["message", "user", "event"]
    assert [i["status"] for i in made] == ["action_taken", "dismissed", "open"]
    assert [i["reason"] for i in made] == ["harassment_or_hate", "other", "spam"]
    assert [i["created_at"] for i in made] == ["2026-10-03T10:00:00+00:00", "2026-10-02T10:00:00+00:00",
                                               "2026-10-01T10:00:00+00:00"]
    assert all(set(i) == BASE_KEYS for i in made)
    assert hist["about"] == []


def test_made_excludes_reports_with_deleted_reporter_and_other_reporters(db):
    _put(db,
         _report(1, "2026-10-01T10:00:00+00:00", reporter_id=None, event_id=EV_ANA),
         _report(2, "2026-10-02T10:00:00+00:00", reporter_id=ANA, event_id=EV_ANA),
         _report(3, "2026-10-03T10:00:00+00:00", reporter_id=TOM, event_id=EV_ANA))
    assert _ids(_history()["made"]) == [3]


def test_made_report_about_the_users_own_event_is_in_both_lists(db):
    _put(db, _report(1, "2026-10-01T10:00:00+00:00", reporter_id=TOM, event_id=EV_TOM))
    hist = _history()
    assert _ids(hist["made"]) == [1] and _ids(hist["about"]) == [1]
    assert hist["about"][0]["event"]["id"] == EV_TOM


def test_same_user_as_reporter_and_as_reported(db):
    _put(db,
         _user_report(1, "2026-10-01T10:00:00+00:00", reporter_id=ANA, about=TOM),          # about TOM
         _user_report(2, "2026-10-02T10:00:00+00:00", reporter_id=TOM, about=ANA),          # made by TOM
         _user_report(3, "2026-10-03T10:00:00+00:00", reporter_id=TOM, about=MIA),          # made by TOM
         _msg_report(4, "2026-10-04T10:00:00+00:00", reporter_id=MIA, about=TOM, event_id=EV_ANA))  # about TOM
    hist = _history()
    assert _ids(hist["about"]) == [4, 1]
    assert _ids(hist["made"]) == [3, 2]


def test_history_of_one_user_does_not_leak_into_another(db):
    _put(db,
         _user_report(1, "2026-10-01T10:00:00+00:00", reporter_id=ANA, about=TOM),
         _user_report(2, "2026-10-02T10:00:00+00:00", reporter_id=TOM, about=ANA))
    ana = _history(ANA)
    assert _ids(ana["about"]) == [2] and _ids(ana["made"]) == [1]
    tom = _history(TOM)
    assert _ids(tom["about"]) == [1] and _ids(tom["made"]) == [2]


# ---- ordering and paging -----------------------------------------------------------------

def test_both_lists_newest_first_by_created_at_not_by_id(db):
    _put(db,
         _user_report(10, "2026-10-01T10:00:00+00:00", reporter_id=ANA),
         _user_report(2, "2026-10-05T10:00:00+00:00", reporter_id=ANA),
         _user_report(5, "2026-10-03T10:00:00+00:00", reporter_id=ANA),
         _user_report(11, "2026-10-01T10:00:00+00:00", reporter_id=TOM, about=ANA),
         _user_report(3, "2026-10-05T10:00:00+00:00", reporter_id=TOM, about=ANA),
         _user_report(7, "2026-10-03T10:00:00+00:00", reporter_id=TOM, about=ANA))
    hist = _history()
    assert _ids(hist["about"]) == [2, 5, 10]
    assert _ids(hist["made"]) == [3, 7, 11]


def test_both_lists_break_created_at_ties_by_id_descending(db):
    same = "2026-10-05T10:00:00+00:00"
    _put(db,
         _user_report(3, same, reporter_id=ANA),
         _user_report(12, same, reporter_id=ANA),
         _user_report(9, same, reporter_id=ANA),
         _user_report(4, same, reporter_id=TOM, about=ANA),
         _user_report(20, same, reporter_id=TOM, about=ANA),
         _user_report(8, same, reporter_id=TOM, about=ANA))
    hist = _history()
    assert _ids(hist["about"]) == [12, 9, 3]  # numeric, not text: 12 before 9
    assert _ids(hist["made"]) == [20, 8, 4]


def test_about_orders_user_message_and_event_reports_as_one_list_with_id_tiebreak(db):
    same = "2026-10-05T10:00:00+00:00"
    _put(db,
         _msg_report(4, same, event_id=EV_ANA, reporter_id=ANA),
         _report(5, same, event_id=EV_TOM, reporter_id=ANA),
         _user_report(6, same, reporter_id=ANA),
         _report(7, "2026-10-01T10:00:00+00:00", event_id=EV_TOM2, reporter_id=ANA),
         _user_report(1, "2026-10-09T10:00:00+00:00", reporter_id=ANA))
    assert _ids(_history()["about"]) == [1, 6, 5, 4, 7]


def test_lists_are_not_paged(db):
    n = 120
    _put(db, *[_user_report(i, f"2026-09-{(i % 28) + 1:02d}T10:{i % 60:02d}:00+00:00", reporter_id=ANA)
               for i in range(1, n + 1)])
    _put(db, *[_user_report(1000 + i, f"2026-09-{(i % 28) + 1:02d}T11:{i % 60:02d}:00+00:00",
                            reporter_id=TOM, about=ANA) for i in range(1, n + 1)])
    hist = _history()
    assert len(hist["about"]) == n and len(hist["made"]) == n
    assert sorted(_ids(hist["about"])) == list(range(1, n + 1))
    assert sorted(_ids(hist["made"])) == [1000 + i for i in range(1, n + 1)]


# ---- administrator details -------------------------------------------------------------------

def test_administrator_details_have_null_report_history(db):
    body = _user(ADM2)
    assert "report_history" in body, f"report_history missing, keys: {sorted(body)}"
    assert body["report_history"] is None
    assert body["is_admin"] is True


def test_administrator_details_null_even_with_reports_about_and_made(db):
    _put(db,
         _user_report(1, "2026-10-01T10:00:00+00:00", about=ADM2, reporter_id=MIA),
         _report(2, "2026-10-02T10:00:00+00:00", event_id=EV_ADM2, reporter_id=MIA),
         _user_report(3, "2026-10-03T10:00:00+00:00", about=MIA, reporter_id=ADM2),
         _report(4, "2026-10-04T10:00:00+00:00", event_id=EV_TOM, reporter_id=ADM2))
    body = _user(ADM2)
    assert "report_history" in body, f"report_history missing, keys: {sorted(body)}"
    assert body["report_history"] is None


def test_regular_user_history_is_unaffected_by_administrator_reports(db):
    _put(db, _user_report(1, "2026-10-01T10:00:00+00:00", about=TOM, reporter_id=ADM2),
         _user_report(2, "2026-10-02T10:00:00+00:00", about=ADM2, reporter_id=TOM))
    hist = _history()
    assert _ids(hist["about"]) == [1] and _ids(hist["made"]) == [2]


# ---- GET /api/admin/account: reports_closed ----------------------------------------------------

def _closed_count():
    body = _account()
    assert "reports_closed" in body, f"reports_closed missing from the response, keys: {sorted(body)}"
    return body["reports_closed"]


def test_reports_closed_counts_dismissed_and_action_taken_by_this_admin(db):
    _put(db,
         _report(1, "2026-10-01T10:00:00+00:00", **_closed()),
         _report(2, "2026-10-02T10:00:00+00:00", **_closed(status="action_taken", outcome="warned")),
         _report(3, "2026-10-03T10:00:00+00:00", **_closed(status="action_taken", outcome="suspended")),
         _report(4, "2026-10-04T10:00:00+00:00", **_closed(status="action_taken", outcome="content_removed")))
    assert _closed_count() == 4


def test_reports_closed_excludes_other_admins_and_open_reports(db):
    _put(db,
         _report(1, "2026-10-01T10:00:00+00:00", **_closed()),
         _report(2, "2026-10-02T10:00:00+00:00", **_closed(by=ADM2)),
         _report(3, "2026-10-03T10:00:00+00:00", **_closed(by=ADM2, status="action_taken", outcome="warned")),
         _report(4, "2026-10-04T10:00:00+00:00"),
         _report(5, "2026-10-05T10:00:00+00:00", reporter_id=ANA))
    assert _closed_count() == 1


def test_reports_closed_is_zero_for_an_admin_who_closed_none(db):
    _put(db,
         _report(1, "2026-10-01T10:00:00+00:00"),
         _report(2, "2026-10-02T10:00:00+00:00", **_closed(by=ADM2)))
    assert _closed_count() == 0


def test_reports_closed_is_zero_with_no_reports_at_all(db):
    assert _closed_count() == 0


def test_reports_closed_is_an_int_not_a_string_or_null(db):
    _put(db, _report(1, "2026-10-01T10:00:00+00:00", **_closed()))
    value = _closed_count()
    assert isinstance(value, int) and not isinstance(value, bool)
    assert value == 1
    db.tables["reports"].clear()
    zero = _closed_count()
    assert zero == 0 and isinstance(zero, int) and not isinstance(zero, bool)


def test_reports_closed_follows_the_signed_in_administrator(db):
    _put(db,
         _report(1, "2026-10-01T10:00:00+00:00", **_closed(by=ADM)),
         _report(2, "2026-10-02T10:00:00+00:00", **_closed(by=ADM2)),
         _report(3, "2026-10-03T10:00:00+00:00", **_closed(by=ADM2)))
    assert _closed_count() == 1
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id=ADM2)
    assert _closed_count() == 2


# ---- no existing field changes (guards; these pass before the feature exists) --------------------

def test_existing_user_details_fields_are_unchanged(db):
    db.tables["friendships"].append({"id": 1, "user_id": TOM, "friend_id": MIA})
    db.tables["user_blocks"].extend([{"blocker_id": TOM, "blocked_id": ANA},
                                     {"blocker_id": MIA, "blocked_id": TOM}])
    db.tables["event_participants"].append({"event_id": EV_ANA, "user_id": TOM})
    db.tables["warnings"].extend([{"id": 1, "user_id": TOM, "admin_id": ADM, "reason": "x", "withdrawn_at": None},
                                  {"id": 2, "user_id": TOM, "admin_id": ADM, "reason": "y", "withdrawn_at": None}])
    _put(db, _user_report(1, "2026-10-01T10:00:00+00:00"))  # reports must not disturb the old fields
    body = _user(TOM)
    expected_keys = {"id", "username", "full_name", "display_name", "avatar_url", "avatar_kind", "icon_id",
                     "created_at", "is_admin", "admin_since", "role", "warnings", "warning_history",
                     "organized_events", "joined_events", "profile_visibility", "status", "suspended_since",
                     "suspension_reason", "warning_count", "friends", "blocked_users", "blocked_by"}
    assert expected_keys <= set(body), f"missing: {sorted(expected_keys - set(body))}"
    assert body["id"] == TOM and body["username"] == "tom" and body["full_name"] == "Tom"
    assert body["display_name"] == "tom" and body["role"] == "user" and body["is_admin"] is False
    assert body["admin_since"] is None
    assert body["avatar_kind"] == "photo" and body["avatar_url"] == "https://img/tom.png"
    assert body["created_at"] == "2026-01-01T00:00:00+00:00"
    assert body["warnings"] == [] and body["warning_history"] == []
    assert body["profile_visibility"] == "public" and body["status"] == "active"
    assert body["suspended_since"] is None and body["warning_count"] == 2
    assert sorted(e["id"] for e in body["organized_events"]["upcoming"]) == sorted([EV_TOM, EV_TOM2])
    assert body["organized_events"]["past"] == [] and body["organized_events"]["cancelled"] == []
    assert [e["id"] for e in body["joined_events"]["upcoming"]] == [EV_ANA]
    assert [p["id"] for p in body["friends"]] == [MIA]
    assert [p["id"] for p in body["blocked_users"]] == [ANA]
    assert [p["id"] for p in body["blocked_by"]] == [MIA]


def test_existing_administrator_details_fields_are_unchanged(db):
    body = _user(ADM2)
    assert body["id"] == ADM2 and body["username"] == "boss2" and body["is_admin"] is True
    assert body["role"] == "administrator" and body["admin_since"] == "2026-04-01T12:00:00+00:00"
    assert body["warnings"] == [] and body["warning_history"] == []
    assert body["profile_visibility"] is None and body["status"] is None and body["warning_count"] is None
    assert body["friends"] == [] and body["blocked_users"] == [] and body["blocked_by"] == []


def test_existing_account_fields_are_unchanged(db):
    _put(db, _report(1, "2026-10-01T10:00:00+00:00", **_closed()))
    body = _account()
    for key in ("id", "email", "username", "full_name", "avatar_url", "avatar_kind", "icon_id",
                "admin_since", "role"):
        assert key in body, f"{key} missing"
    assert body["id"] == ADM and body["username"] == "boss" and body["full_name"] == "Boss"
    assert body["avatar_url"] == "https://img/boss.png" and body["avatar_kind"] == "photo"
    assert body["icon_id"] is None
    assert body["admin_since"] == "2026-03-01T12:00:00+00:00"
    assert body["role"] == "administrator"


# ---- in_() chunking of the event-report lookup --------------------------------------------------

@pytest.fixture
def in_spy(monkeypatch):
    """Lengths of every in_() list used on the reports table; a list over LOOKUP_CHUNK is refused."""
    lengths = []
    original = _fake_supabase.FakeQuery.in_

    def spy(self, col, vals):
        vals = list(vals)
        if self.name == "reports":
            lengths.append(len(vals))
            if len(vals) > LOOKUP_CHUNK:
                raise AssertionError(f"in_({col!r}) got {len(vals)} ids, more than LOOKUP_CHUNK={LOOKUP_CHUNK}")
        return original(self, col, vals)

    monkeypatch.setattr(_fake_supabase.FakeQuery, "in_", spy)
    return lengths


def _tom_events(db, n):
    """Replace TOM's events with n generated ones; returns their ids."""
    ids = [f"e0000000-0000-4000-8000-{i:012d}" for i in range(1, n + 1)]
    db.tables["events"] = [e for e in db.tables["events"] if e["created_by"] != TOM]
    db.tables["events"].extend(_event(eid, f"Event {i}", TOM) for i, eid in enumerate(ids, 1))
    return ids


def _assert_chunk_rule(lengths, more_than_one_chunk):
    """Every in_() list on reports is non-empty and at most LOOKUP_CHUNK; a full chunk is used when more are needed."""
    assert lengths, "the in_() spy was never hit"
    assert all(0 < n <= LOOKUP_CHUNK for n in lengths), lengths
    if more_than_one_chunk:
        assert max(lengths) == LOOKUP_CHUNK, lengths


def test_event_reports_for_more_than_two_chunks_of_events_are_all_found_in_chunked_lookups(db, in_spy):
    n = 230
    ids = _tom_events(db, n)
    # created_at varies (several reports share an instant, exercising the id tiebreak)
    _put(db, *[_report(i, f"2026-09-{(i % 28) + 1:02d}T10:{i % 60:02d}:00+00:00", event_id=ids[i - 1])
               for i in range(1, n + 1)])
    about = _history()["about"]
    assert len(about) == n and sorted(_ids(about)) == list(range(1, n + 1))
    for entry in about:
        assert entry["target_type"] == "event"
        assert entry["event"] == {"id": ids[entry["id"] - 1], "title": f"Event {entry['id']}"}
    keys = [(e["created_at"], e["id"]) for e in about]
    assert keys == sorted(keys, reverse=True)
    _assert_chunk_rule(in_spy, more_than_one_chunk=True)


def test_exactly_one_chunk_of_events_uses_a_single_in_call(db, in_spy):
    ids = _tom_events(db, LOOKUP_CHUNK)
    _put(db, _report(1, "2026-10-01T10:00:00+00:00", event_id=ids[-1]))
    assert _ids(_history()["about"]) == [1]
    _assert_chunk_rule(in_spy, more_than_one_chunk=False)


def test_event_report_only_on_the_first_event_of_the_second_chunk_is_found(db, in_spy):
    ids = _tom_events(db, LOOKUP_CHUNK + 1)
    _put(db, _report(1, "2026-10-01T10:00:00+00:00", event_id=ids[LOOKUP_CHUNK]))
    about = _history()["about"]
    assert _ids(about) == [1]
    assert about[0]["event"] == {"id": ids[LOOKUP_CHUNK], "title": f"Event {LOOKUP_CHUNK + 1}"}
    _assert_chunk_rule(in_spy, more_than_one_chunk=True)


def test_organizer_without_events_makes_no_event_report_in_call(db, in_spy):
    _tom_events(db, 0)
    _put(db, _user_report(1, "2026-10-01T10:00:00+00:00"),
         _report(2, "2026-10-02T10:00:00+00:00", reporter_id=TOM, event_id=EV_ANA))
    hist = _history()
    assert _ids(hist["about"]) == [1] and _ids(hist["made"]) == [2]
    assert in_spy == []
    db.tables["reports"].clear()
    assert _history() == {"about": [], "made": []}
    assert in_spy == []


# ---- mixed-precision timestamps ---------------------------------------------------------------------

def test_both_lists_order_mixed_precision_timestamps_chronologically_with_id_tiebreak(db):
    ts = {"whole": "2026-10-28T18:02:11+00:00", "half": "2026-10-28T18:02:11.5+00:00",
          "micro": "2026-10-28T18:02:11.482113+00:00", "centi": "2026-10-28T18:02:11.48+00:00",
          "before": "2026-10-28T18:02:10.999999+00:00"}
    _put(db,
         _user_report(1, ts["whole"], reporter_id=ANA), _user_report(2, ts["half"], reporter_id=ANA),
         _user_report(3, ts["micro"], reporter_id=ANA), _user_report(4, ts["centi"], reporter_id=ANA),
         _user_report(5, ts["before"], reporter_id=ANA), _user_report(6, ts["whole"], reporter_id=ANA),
         _user_report(11, ts["whole"], reporter_id=TOM, about=ANA), _user_report(12, ts["half"], reporter_id=TOM, about=ANA),
         _user_report(13, ts["micro"], reporter_id=TOM, about=ANA), _user_report(14, ts["centi"], reporter_id=TOM, about=ANA),
         _user_report(15, ts["before"], reporter_id=TOM, about=ANA), _user_report(16, ts["whole"], reporter_id=TOM, about=ANA))
    hist = _history()
    assert _ids(hist["about"]) == [2, 3, 4, 6, 1, 5]  # equal instants (6, 1): highest id first
    assert _ids(hist["made"]) == [12, 13, 14, 16, 11, 15]


# ---- a server that caps every response below the data size (PostgREST max_rows) ---------------------------

ROW_CAP = 50


@pytest.fixture
def row_cap(monkeypatch):
    """Cut every select response to ROW_CAP rows AFTER range/limit; the exact count still counts all matches."""
    state = {"cut": 0}
    original = _fake_supabase.FakeQuery.execute

    def capped(self):
        res = original(self)
        if self.action == "select" and isinstance(res.data, list) and len(res.data) > ROW_CAP:
            state["cut"] += 1
            res.data = res.data[:ROW_CAP]
        return res

    monkeypatch.setattr(_fake_supabase.FakeQuery, "execute", capped)
    return state


def _ts(i):
    """Distinct instants, with every pair sharing one so the id tiebreak is exercised too."""
    minute = i // 2
    return f"2026-09-{(minute // 1440) + 1:02d}T{(minute // 60) % 24:02d}:{minute % 60:02d}:00+00:00"


def test_every_list_is_complete_when_the_server_caps_responses(db, row_cap):
    ids = _tom_events(db, 120)
    _put(db, *[_user_report(i, _ts(i), reporter_id=ANA) for i in range(1, 131)])                   # about TOM
    _put(db, *[_user_report(1000 + i, _ts(i), reporter_id=TOM, about=ANA) for i in range(1, 131)])  # made by TOM
    _put(db, *[_report(2000 + i, _ts(i), event_id=ids[i - 1], reporter_id=MIA) for i in range(1, 121)])
    hist = _history()
    assert row_cap["cut"] > 0, "the cap was never hit, the test would pass vacuously"

    expected_about = sorted([(_ts(i), i, None) for i in range(1, 131)]
                            + [(_ts(i), 2000 + i, ids[i - 1]) for i in range(1, 121)], reverse=True)
    assert _ids(hist["about"]) == [rid for _, rid, _ in expected_about]
    for entry, (_, rid, event_id) in zip(hist["about"], expected_about):
        if event_id is None:
            assert entry["event"] is None and entry["target_type"] == "user"
        else:
            assert entry["event"] == {"id": event_id, "title": f"Event {rid - 2000}"}
            assert entry["target_type"] == "event"
        assert set(entry) == BASE_KEYS | {"event"}
    expected_made = sorted([(_ts(i), 1000 + i) for i in range(1, 131)], reverse=True)
    assert _ids(hist["made"]) == [rid for _, rid in expected_made]
    assert all(set(e) == BASE_KEYS for e in hist["made"])


def test_reports_closed_is_the_full_count_when_the_server_caps_responses(db, row_cap):
    _put(db, *[_report(i, _ts(i), reporter_id=ANA, **_closed()) for i in range(1, 131)])
    _put(db, *[_report(1000 + i, _ts(i), **_closed(by=ADM2)) for i in range(1, 11)])
    assert _closed_count() == 130


def test_reports_closed_falls_back_to_a_complete_paged_count_when_the_count_header_is_missing(db, row_cap,
                                                                                            monkeypatch):
    _put(db, *[_report(i, _ts(i), reporter_id=ANA, **_closed()) for i in range(1, 131)])
    capped = _fake_supabase.FakeQuery.execute  # already wraps the real execute with the cap

    def no_count(self):
        res = capped(self)
        res.count = None
        return res

    monkeypatch.setattr(_fake_supabase.FakeQuery, "execute", no_count)
    assert _closed_count() == 130
    assert row_cap["cut"] > 0


# ---- the closed-reports count asks for one row only ------------------------------------------------------

def test_reports_closed_query_asks_for_at_most_one_row(db, monkeypatch):
    _put(db, *[_report(i, _ts(i), reporter_id=ANA, **_closed()) for i in range(1, 8)])
    seen = []
    original_eq, original_execute = _fake_supabase.FakeQuery.eq, _fake_supabase.FakeQuery.execute

    def eq(self, col, val):
        self.eq_cols = getattr(self, "eq_cols", []) + [col]
        return original_eq(self, col, val)

    def execute(self):
        res = original_execute(self)
        if self.name == "reports" and "closed_by" in getattr(self, "eq_cols", []):
            seen.append((self.window, len(res.data), res.count))
        return res

    monkeypatch.setattr(_fake_supabase.FakeQuery, "eq", eq)
    monkeypatch.setattr(_fake_supabase.FakeQuery, "execute", execute)
    assert _closed_count() == 7
    assert len(seen) == 1, seen
    window, rows_returned, count = seen[0]
    assert window is not None and window[1] - window[0] + 1 <= 1, f"closed_by query is not limited to one row: {window}"
    assert rows_returned <= 1 and count == 7


# ---- request cost of a normal user ----------------------------------------------------------------------

def test_a_normal_user_costs_one_request_per_lookup(db, monkeypatch):
    _put(db, _user_report(1, "2026-10-01T10:00:00+00:00"), _report(2, "2026-10-02T10:00:00+00:00", event_id=EV_TOM),
         _user_report(3, "2026-10-03T10:00:00+00:00", reporter_id=TOM, about=ANA))
    calls = []
    original = _fake_supabase.FakeQuery.execute

    def execute(self):
        if self.name in ("reports", "events") and self.cols != "*" and ("id, title" in self.cols or "reason" in self.cols):
            calls.append(self.name)
        return original(self)

    monkeypatch.setattr(_fake_supabase.FakeQuery, "execute", execute)
    from app.services import admin_report_history_service as svc
    svc.report_history(TOM)
    # about (user reports), organizer events, event reports (one chunk), made
    assert sorted(calls) == ["events", "reports", "reports", "reports"]
