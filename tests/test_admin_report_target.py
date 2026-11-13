"""Ticket #262 phase 1: the report details carry the warn/suspend target.

  GET /api/admin/reports/{id} (and assign / unassign / dismiss / action, which reuse get_report_details)
  additionally return `target_user` (PersonSummary or null) and `target_user_is_admin` (bool).

target_user is the profile resolve_target gives warn/suspend: the reported user (user and message report)
or the organizer of the event (event report). It is null only when that profile no longer exists.
target_user_is_admin is live and always equals reported_user_is_administrator.

Uses the world and fixtures of tests/test_admin_reports_actions.py (TOM is the target in every kind).
"""
import pytest
from fastapi import HTTPException

from app.services import admin_report_service
from app.services.admin_report_action_service import resolve_target
from tests import _fake_supabase
from tests.test_admin_reports_actions import (  # noqa: F401  (db fixture)
    ACTION_OUTCOME, ADM, ADM2, COMBOS, EV1, MIA, MSG, PERSON_KEYS, REASON, TOM, _act, _build_user_summary, _code, _detail, _dismiss,
    _event_row, _make_admin, _profile_row, _row, _seed, client, db,
)

def _drop_profile(db, uid=TOM):
    db.tables["profiles"] = [p for p in db.tables["profiles"] if p["id"] != uid]


def _soft_remove_event(db):
    _event_row(db)["removed_at"] = "2026-10-20T00:00:00+00:00"


def _event_gone(db):
    db.tables["events"] = [e for e in db.tables["events"] if e["id"] != EV1]


def _noop(db):
    pass


def _null_organizer(db):
    _event_row(db)["created_by"] = None


# (id, kind, seed kwargs, mutate, expected target id, expected is_admin)
SCENARIOS = [
    ("user_regular", "user", {}, _noop, TOM, False),
    ("user_admin", "user", {}, _make_admin, TOM, True),
    ("user_deleted", "user", {}, _drop_profile, None, False),
    ("message_regular", "message", {}, _noop, TOM, False),
    ("message_admin", "message", {}, _make_admin, TOM, True),
    ("message_deleted_author", "message", {}, _drop_profile, None, False),
    ("event_regular", "event", {}, _noop, TOM, False),
    ("event_admin", "event", {}, _make_admin, TOM, True),
    ("event_deleted_organizer", "event", {}, _drop_profile, None, False),
    ("event_soft_removed", "event", {}, _soft_remove_event, TOM, False),
    ("event_hard_deleted_id_null", "event", {"event_id": None}, _noop, None, False),
    ("event_row_missing", "event", {}, _event_gone, None, False),
    ("event_created_by_null", "event", {}, _null_organizer, None, False),
    ("message_reported_user_null", "message", {"reported_user_id": None}, _noop, None, False),
]
IDS = [s[0] for s in SCENARIOS]


def _setup(db, kind, kwargs, mutate):
    _seed(db, kind, **kwargs)
    mutate(db)


# ---- (1) scenario matrix ----------------------------------------------------------------------

@pytest.mark.parametrize("name,kind,kwargs,mutate,target,is_admin", SCENARIOS, ids=IDS)
def test_details_target_user_and_flag(db, name, kind, kwargs, mutate, target, is_admin):
    _setup(db, kind, kwargs, mutate)
    body = _detail()
    assert "target_user" in body and "target_user_is_admin" in body
    if target is None:
        assert body["target_user"] is None
    else:
        assert body["target_user"]["id"] == target
        assert body["target_user"]["username"] == "tom"
        assert body["target_user"] == _build_user_summary(_profile_row(db, target))
    assert body["target_user_is_admin"] is is_admin


# ---- (2) always equals reported_user_is_administrator -------------------------------------------

@pytest.mark.parametrize("name,kind,kwargs,mutate,target,is_admin", SCENARIOS, ids=IDS)
def test_target_user_is_admin_equals_reported_user_is_administrator(db, name, kind, kwargs, mutate, target, is_admin):
    _setup(db, kind, kwargs, mutate)
    body = _detail()
    assert "target_user_is_admin" in body
    assert body["target_user_is_admin"] is body["reported_user_is_administrator"]


# ---- (3) parity with resolve_target ---------------------------------------------------------------

@pytest.mark.parametrize("name,kind,kwargs,mutate,target,is_admin", SCENARIOS, ids=IDS)
def test_target_user_matches_resolve_target(db, name, kind, kwargs, mutate, target, is_admin):
    _setup(db, kind, kwargs, mutate)
    body = _detail()
    assert "target_user" in body
    try:
        resolved = resolve_target(_row(db))
    except HTTPException as e:
        assert e.status_code == 404 and e.detail["code"] == "reported_user_not_found"
        assert body["target_user"] is None
    else:
        assert body["target_user"] is not None
        assert body["target_user"]["id"] == resolved["id"]


def test_message_report_target_user_is_the_reported_user(db):
    _seed(db, "message")
    body = _detail()
    assert body["reported"]["user"] is not None
    assert "target_user" in body
    assert body["target_user"] == body["reported"]["user"]


# ---- (4) shape --------------------------------------------------------------------------------------

@pytest.mark.parametrize("kind", ["user", "message", "event"])
def test_target_user_has_exactly_the_person_summary_keys(db, kind):
    _seed(db, kind)
    body = _detail()
    assert body.get("target_user") is not None
    assert set(body["target_user"]) == PERSON_KEYS


# ---- (6) action endpoint responses ----------------------------------------------------------------

def _assert_carries_target(body):
    assert "target_user" in body and "target_user_is_admin" in body
    assert body["target_user"]["id"] == TOM and body["target_user"]["username"] == "tom"
    assert body["target_user_is_admin"] is False


def test_assign_response_carries_target(db):
    _seed(db, "event", assigned_to=None)
    res = client.post("/api/admin/reports/1/assign", json={"admin_id": ADM})
    assert res.status_code == 200, res.text
    _assert_carries_target(res.json())


def test_unassign_response_carries_target(db):
    _seed(db, "message")
    res = client.post("/api/admin/reports/1/unassign")
    assert res.status_code == 200, res.text
    _assert_carries_target(res.json())


def test_dismiss_response_carries_target(db):
    _seed(db, "user")
    res = _dismiss()
    assert res.status_code == 200, res.text
    _assert_carries_target(res.json())


@pytest.mark.parametrize("kind,action", COMBOS)
def test_action_response_carries_target(db, kind, action):
    _seed(db, kind)
    res = _act(action=action, reason=None if action == "remove_content" else REASON)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["outcome"] == ACTION_OUTCOME[action]
    _assert_carries_target(body)       # a soft-removed event keeps its organizer; the flag stays false


# ---- (7) pre-existing keys keep their values ------------------------------------------------------------

def _person(db, uid):
    return _build_user_summary(_profile_row(db, uid))


def _card(title="Board game night"):
    return {"id": EV1, "title": title, "name": title,
            "banner": f"https://img/{title}.jpg", "banner_url": f"https://img/{title}.jpg"}


def test_existing_fields_unchanged_for_user_report(db):
    _seed(db, "user")
    body = _detail()
    assert body["id"] == 1 and body["status"] == "open" and body["reason"] == "harassment_or_hate"
    assert body["target_type"] == "user" and body["origin"] == "profile" and body["description"] is None
    assert body["reporter"] == _person(db, MIA)
    assert body["assigned_to"] == _person(db, ADM)
    assert body["reported"] == {"type": "user", "event": None, "user": _person(db, TOM), "message": None}
    assert body["event"] is None and body["chat_context"] is None
    assert body["outcome"] is None and body["closed_by"] is None and body["closed_at"] is None
    assert body["content_removed"] is False and body["reported_user_is_administrator"] is False


def test_existing_fields_unchanged_for_message_report(db):
    _seed(db, "message")
    body = _detail()
    assert body["target_type"] == "message" and body["origin"] == "event_chat"
    assert body["reported"] == {"type": "message", "event": _card(), "user": _person(db, TOM),
                                "message": {"id": MSG, "event_id": EV1}}
    assert body["event"] == _card() and body["chat_context"] == []
    assert body["content_removed"] is False and body["reported_user_is_administrator"] is False


def test_existing_fields_unchanged_for_event_report(db):
    _seed(db, "event")
    body = _detail()
    assert body["target_type"] == "event" and body["origin"] == "event_details"
    assert body["reported"] == {"type": "event", "event": _card(), "user": None, "message": None}
    assert body["event"] == _card() and body["chat_context"] is None
    assert body["content_removed"] is False and body["reported_user_is_administrator"] is False


# ---- (8) queries: the organizer rides the existing batch -------------------------------------------------

def test_event_report_details_load_the_organizer_in_the_one_people_batch(db, monkeypatch):
    _seed(db, "event")
    people_calls, role_calls, profile_selects = [], [], []
    real_people, real_role = admin_report_service._people_by_id, admin_report_service._role_of

    def people(ids):
        ids = list(ids)
        people_calls.append(ids)
        return real_people(ids)

    def role(uid):
        role_calls.append(uid)
        return real_role(uid)

    real_execute = _fake_supabase.FakeQuery.execute

    def execute(self):
        if self.name == "profiles" and self.action == "select":
            profile_selects.append(self)
        return real_execute(self)

    monkeypatch.setattr(admin_report_service, "_people_by_id", people)
    monkeypatch.setattr(admin_report_service, "_role_of", role)
    monkeypatch.setattr(_fake_supabase.FakeQuery, "execute", execute)

    body = _detail()
    assert body.get("target_user") is not None and body["target_user"]["id"] == TOM
    assert len(people_calls) == 1, people_calls
    assert TOM in people_calls[0]
    assert role_calls == [TOM]
    assert len(profile_selects) == 2    # one batched people select + one role select, nothing per person


# ---- (9) race: promoted after the details were read -----------------------------------------------------

def test_target_promoted_after_details_read_still_refused_on_warn(db):
    _seed(db, "message")
    first = _detail()
    assert first.get("target_user_is_admin") is False and first["target_user"]["id"] == TOM
    _make_admin(db)
    res = _act(action="warn")
    assert res.status_code == 400, res.text
    assert _code(res) == "reported_user_is_administrator"
    again = _detail()
    assert again["target_user_is_admin"] is True and again["reported_user_is_administrator"] is True


@pytest.mark.parametrize("role,who", [("reporter", MIA), ("assignee", ADM)])
def test_organizer_who_is_also_reporter_or_assignee_is_loaded_once(db, monkeypatch, role, who):
    _seed(db, "event")
    _event_row(db)["created_by"] = who
    people_calls = []
    real_people = admin_report_service._people

    def people(ids):
        ids = list(ids)
        people_calls.append(ids)
        return real_people(ids)

    monkeypatch.setattr(admin_report_service, "_people", people)
    body = _detail()
    assert body["target_user"] is not None and body["target_user"]["id"] == who
    assert body["target_user"] == _build_user_summary(_profile_row(db, who))
    assert len(people_calls) == 1, people_calls
    assert len(people_calls[0]) == len(set(people_calls[0])), people_calls
    assert who in people_calls[0]
