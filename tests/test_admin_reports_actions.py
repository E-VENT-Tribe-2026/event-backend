"""Ticket #235 phase 3: dismiss and act on a report (happy paths, refusals, races, request validation).

  POST /api/admin/reports/{report_id}/dismiss
  POST /api/admin/reports/{report_id}/action     {"action": "warn"|"suspend"|"remove_content", "reason": "..."}

Driven through HTTP against the real app. The REAL warning, suspension and content-removal services
run against the in-memory Supabase fake (tests/_fake_supabase.py); the tests assert on the resulting
table state (warnings, profiles.suspended_at, events/event_chats.removed_*, the reports row, logs).
Only external side effects are patched (participant emails, the reminder-service email lookup).
Nothing here patches an internal service function, so the implementation may import and call the
services however it likes.

Covered here: dismiss and every action (warn, suspend, remove_content) for user, message and event
reports; the refusals (closed report, administrator target, already suspended, content already removed,
reported user gone) with nothing written; the claim race between two administrators; a failure of the
reused service after the claim (the report is reopened); request validation; the details after each
outcome; the admin-only chain. Failures that happen AFTER the service's work was done, a failing reopen,
failing detail loads and races between validation and the service are in
tests/test_admin_reports_action_failures.py.

Conventions encoded here:
  * audit action names: "report_dismissed" and "report_action_taken", entity_type "report",
    entity_id = str(report id); the details values hold "outcome:<outcome>" (and "action:<action>").
  * 404 reported_user_not_found for warn/suspend when the reported user / organizer is gone.
"""
import base64
import copy
import importlib
import json
import pkgutil
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.services as services_pkg
from app.core.dependencies import require_admin
from app.main import app
from app.schemas.suspension_schema import SUSPENSION_REASON_MAX_LENGTH
from app.schemas.warning_schema import WARNING_REASON_MAX_LENGTH
from app.services.admin_service import _build_user_summary
from tests import _fake_supabase
from tests._fake_supabase import FakeSupabase

ADM = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"    # the acting administrator
ADM2 = "abababab-abab-4bab-8bab-abababababab"   # another administrator
MIA = "11111111-1111-4111-8111-111111111111"    # reporter
TOM = "22222222-2222-4222-8222-222222222222"    # reported user / message author / event organizer
ANA = "33333333-3333-4333-8333-333333333333"    # bystander (joined the event)
EV1 = "550e8400-e29b-41d4-a716-446655440000"    # organized by TOM
EV2 = "9b2f3c1e-6a47-4c0e-8d55-0f1a2b3c4d5e"    # organized by ANA
MSG = 42                                         # chat message by TOM in EV1
OTHER_MSG = 43                                   # chat message by ANA in EV1

REASON = "Repeated insults in the event chat."
TS = "2026-10-01T10:00:00+00:00"
OLD_CLOSE = "2026-10-09T00:00:00+00:00"

client = TestClient(app)
SKIP_MODULES = {"block_visibility", "removed_content"}  # conftest patches these itself

KINDS = ("user", "message", "event")
ACTION_OUTCOME = {"warn": "warned", "suspend": "suspended", "remove_content": "content_removed"}
COMBOS = ([(k, a) for a in ("warn", "suspend") for k in KINDS]
          + [("event", "remove_content"), ("message", "remove_content")])
PERSON_KEYS = {"id", "username", "full_name", "display_name", "avatar_kind", "icon_id", "avatar_url"}
DETAIL_KEYS = {"id", "status", "reason", "description", "created_at", "origin", "reporter", "target_type",
               "reported", "event", "chat_context", "outcome", "closed_by", "closed_at", "content_removed",
               "reported_user_is_administrator"}


# ---- world --------------------------------------------------------------------------------------

def _profile(uid, username, role="user"):
    return {"id": uid, "username": username, "full_name": username.title(), "role": role,
            "avatar_url": f"https://img/{username}.png", "avatar_kind": "photo", "icon_id": None,
            "visibility": "public", "created_at": "2026-01-01T00:00:00+00:00",
            "suspended_at": None, "suspension_reason": None}


def _event(eid, title, created_by):
    return {"id": eid, "title": title, "created_by": created_by, "banner_url": f"https://img/{title}.jpg",
            "status": "active", "start_datetime": "2099-01-01T00:00:00+00:00",
            "end_datetime": "2099-01-01T02:00:00+00:00", "removed_at": None, "removed_by": None}


def _chat(id_, sender, event_id=EV1, removed_at=None, removed_by=None):
    return {"id": id_, "event_id": event_id, "sender_id": sender, "content": f"msg {id_}", "type": "chat",
            "removed_at": removed_at, "removed_by": removed_by, "created_at": f"2026-10-28T18:00:{id_:02d}+00:00"}


def _report(rid, **kw):
    row = {"id": rid, "reporter_id": MIA, "target_type": "event", "event_id": EV1, "reported_user_id": None,
           "message_id": None, "reason": "spam", "description": None, "origin": "event_details",
           "status": "open", "chat_context": None, "created_at": TS,
           "outcome": None, "closed_by": None, "closed_at": None}
    row.update(kw)
    return row


def _modules_with_supabase():
    mods = [importlib.import_module("app.api.v1.admin_routes")]
    for info in pkgutil.iter_modules(services_pkg.__path__):
        if info.name in SKIP_MODULES:
            continue
        mods.append(importlib.import_module(f"app.services.{info.name}"))
    return [m for m in mods if hasattr(m, "supabase")]


def _build_fake() -> FakeSupabase:
    fake = FakeSupabase()
    fake.tables["profiles"] = [_profile(ADM, "boss", "administrator"), _profile(ADM2, "boss2", "administrator"),
                               _profile(MIA, "mia"), _profile(TOM, "tom"), _profile(ANA, "ana")]
    fake.tables["events"] = [_event(EV1, "Board game night", TOM), _event(EV2, "Sunset party", ANA)]
    fake.tables["event_chats"] = [_chat(MSG, TOM), _chat(OTHER_MSG, ANA)]
    fake.tables["event_participants"] = [{"id": i + 1, "event_id": EV1, "user_id": u, "status": "going"}
                                         for i, u in enumerate((TOM, MIA, ANA))]
    for name in ("reports", "warnings", "notifications", "logs", "user_blocks"):
        fake.tables[name] = []
    return fake


@contextmanager
def _patched(fake):
    """Every `supabase` name in the admin routes and the services points at the fake; the e-mail senders are
    the only external effects and are stubbed (as tests/test_suspension.py does)."""
    patches = [patch.object(m, "supabase", fake) for m in _modules_with_supabase()]
    patches += [
        patch("app.services.event_service._email_participants", lambda *a, **k: None),
        patch("app.services.reminder_service._get_user_email", lambda uid: None),
    ]
    for p in patches:
        p.start()
    try:
        yield fake
    finally:
        for p in patches:
            p.stop()


@pytest.fixture
def db():
    fake = _build_fake()
    with _patched(fake):
        app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id=ADM)
        yield fake
        app.dependency_overrides.clear()


# ---- seeding and reading helpers ----------------------------------------------------------------

def _seed(db, kind, rid=1, **kw) -> int:
    """An open report of the given kind. TOM is the target in all three: reported user (user report),
    message author (message report), organizer (event report)."""
    if kind == "user":
        row = _report(rid, target_type="user", event_id=None, reported_user_id=TOM, origin="profile",
                      reason="harassment_or_hate")
    elif kind == "message":
        row = _report(rid, target_type="message", event_id=EV1, reported_user_id=TOM, message_id=MSG,
                      origin="event_chat", chat_context=[])
    else:
        row = _report(rid)
    row.update(kw)
    db.tables["reports"].append(row)
    return rid


def _row(db, rid=1) -> dict:
    return next(r for r in db.tables["reports"] if r["id"] == rid)


def _profile_row(db, uid) -> dict:
    return next(p for p in db.tables["profiles"] if p["id"] == uid)


def _event_row(db, eid=EV1) -> dict:
    return next(e for e in db.tables["events"] if e["id"] == eid)


def _chat_row(db, mid=MSG) -> dict:
    return next(c for c in db.tables["event_chats"] if c["id"] == mid)


def _warnings(db, user=None) -> list:
    return [w for w in db.tables["warnings"] if user is None or w["user_id"] == user]


def _report_logs(db) -> list:
    return [l for l in db.tables["logs"] if l.get("entity_type") == "report"]


def _snapshot(db) -> dict:
    return copy.deepcopy(db.tables)


def _make_admin(db, uid=TOM):
    _profile_row(db, uid)["role"] = "administrator"


def _dismiss(rid=1):
    return client.post(f"/api/admin/reports/{rid}/dismiss")


def _act(rid=1, action="warn", reason=REASON, **extra):
    body = {"action": action}
    if reason is not None:
        body["reason"] = reason
    body.update(extra)
    return client.post(f"/api/admin/reports/{rid}/action", json=body)


def _code(res) -> str:
    detail = res.json()["detail"]
    assert isinstance(detail, dict), res.text
    assert isinstance(detail["message"], str) and detail["message"]
    return detail["code"]


def _detail(rid=1) -> dict:
    res = client.get(f"/api/admin/reports/{rid}")
    assert res.status_code == 200, res.text
    return res.json()


def _assert_open_unchanged(db, rid=1):
    row = _row(db, rid)
    assert row["status"] == "open", row
    assert row["outcome"] is None and row["closed_by"] is None and row["closed_at"] is None, row


def _assert_untouched(db, before):
    """A refusal changes nothing at all: not the report, not a warning, not a log, not a notification."""
    assert _snapshot(db) == before


def _assert_closed_response(db, res, rid, status, outcome, admin=ADM):
    assert res.status_code == 200, res.text
    body = res.json()
    assert DETAIL_KEYS <= set(body), set(DETAIL_KEYS) - set(body)
    assert body["id"] == rid
    assert body["status"] == status and body["outcome"] == outcome
    assert PERSON_KEYS <= set(body["closed_by"])
    assert body["closed_by"] == _build_user_summary(_profile_row(db, admin))
    assert isinstance(body["closed_at"], str) and datetime.fromisoformat(body["closed_at"])
    row = _row(db, rid)
    assert (row["status"], row["outcome"], row["closed_by"]) == (status, outcome, admin)
    assert row["closed_at"] is not None
    # the response is the same document GET /reports/{id} gives afterwards
    assert body == _detail(rid)


def _assert_closure_audit(db, rid, action, outcome=None, admin=ADM):
    logs = _report_logs(db)
    assert len(logs) == 1, logs
    entry = logs[0]
    assert entry["type"] == action
    assert entry["created_by_id"] == admin
    assert entry["entity_id"] == str(rid)
    assert outcome, "say which outcome the audit entry must carry"
    assert f"outcome:{outcome}" in entry["values"], entry["values"]    # exact entry, not a substring


# ---- failure and race injection -----------------------------------------------------------------

@pytest.fixture
def fail(monkeypatch):
    """Make the fake raise for matching queries: fail.arm(lambda q: ..., error); fail.disarm()."""
    state = SimpleNamespace(when=None, error=None, hits=0)
    original = _fake_supabase.FakeQuery.execute

    def execute(self):
        if state.when is not None and state.when(self):
            state.hits += 1
            raise state.error
        return original(self)

    monkeypatch.setattr(_fake_supabase.FakeQuery, "execute", execute)

    def arm(when, error):
        state.when, state.error = when, error

    state.arm = arm
    state.disarm = lambda: setattr(state, "when", None)
    return state


def _warnings_insert(q):
    return q.name == "warnings" and q.action == "insert"


def _profiles_update(q):
    return q.name == "profiles" and q.action == "update"


def _event_removal_update(q):
    return q.name == "events" and q.action == "update" and "removed_at" in (q.payload or {})


@pytest.fixture
def race(monkeypatch):
    """Another administrator closes the report between this request's checks and its claim: the first
    update that reaches the reports table finds the row already dismissed by ADM2."""
    state = SimpleNamespace(fired=False)
    original = _fake_supabase.FakeQuery.execute

    def execute(self):
        if self.name == "reports" and self.action == "update" and not state.fired:
            state.fired = True
            row = next(r for r in self.db.tables["reports"] if r["id"] == 1)
            row.update(status="dismissed", outcome="dismissed", closed_by=ADM2, closed_at=OLD_CLOSE)
        return original(self)

    monkeypatch.setattr(_fake_supabase.FakeQuery, "execute", execute)
    return state


# ==== dismiss =====================================================================================

@pytest.mark.parametrize("kind", KINDS)
def test_dismiss_open_report_closes_it_with_all_fields_and_audit(db, kind):
    _seed(db, kind)
    res = _dismiss()
    _assert_closed_response(db, res, 1, "dismissed", "dismissed")
    _assert_closure_audit(db, 1, "report_dismissed", "dismissed")
    # dismissing only closes the report
    assert _warnings(db) == []
    assert all(p["suspended_at"] is None for p in db.tables["profiles"])
    assert all(e["removed_at"] is None for e in db.tables["events"])
    assert all(c["removed_at"] is None for c in db.tables["event_chats"])


def test_dismiss_keeps_the_report_content_and_closes_only_that_report(db):
    _seed(db, "event", 1)
    _seed(db, "message", 2)
    assert _dismiss(1).status_code == 200
    assert _row(db, 2)["status"] == "open"
    assert _row(db, 1)["event_id"] == EV1 and _row(db, 1)["reason"] == "spam"


@pytest.mark.parametrize("closed", [
    {"status": "dismissed", "outcome": "dismissed"},
    {"status": "action_taken", "outcome": "warned"},
    {"status": "action_taken", "outcome": "content_removed"},
])
def test_dismiss_closed_report_is_409_report_closed_and_nothing_changes(db, closed):
    _seed(db, "event", closed_by=ADM2, closed_at=OLD_CLOSE, **closed)
    before = _snapshot(db)
    res = _dismiss()
    assert res.status_code == 409, res.text
    assert _code(res) == "report_closed"
    _assert_untouched(db, before)


def test_dismiss_unknown_report_is_404_report_not_found(db):
    _seed(db, "event")
    before = _snapshot(db)
    res = _dismiss(999)
    assert res.status_code == 404, res.text
    assert _code(res) == "report_not_found"
    _assert_untouched(db, before)


def test_dismiss_still_works_when_the_reported_user_is_an_administrator(db):
    _seed(db, "user")
    _make_admin(db)
    res = _dismiss()
    _assert_closed_response(db, res, 1, "dismissed", "dismissed")
    assert _detail()["reported_user_is_administrator"] is True


def test_dismiss_works_when_the_content_is_already_removed_or_deleted(db):
    _seed(db, "event", 1, event_id=None)             # event deleted
    _seed(db, "message", 2)
    _chat_row(db)["removed_at"] = "2026-10-20T00:00:00+00:00"
    assert _dismiss(1).status_code == 200
    assert _dismiss(2).status_code == 200


def test_second_dismiss_is_409_report_closed_and_writes_no_second_audit_entry(db):
    _seed(db, "message")
    assert _dismiss().status_code == 200
    first = (_row(db)["closed_at"], _row(db)["closed_by"])
    res = _dismiss()
    assert res.status_code == 409 and _code(res) == "report_closed"
    assert (_row(db)["closed_at"], _row(db)["closed_by"]) == first
    assert len(_report_logs(db)) == 1


def test_dismiss_conflict_when_another_admin_closes_it_first(db, race):
    _seed(db, "event")
    res = _dismiss()
    assert race.fired, "the claim never touched the reports table"
    assert res.status_code == 409, res.text
    row = _row(db)
    assert (row["status"], row["outcome"], row["closed_by"], row["closed_at"]) == \
           ("dismissed", "dismissed", ADM2, OLD_CLOSE)            # the other admin's closure stands
    assert _report_logs(db) == []                                   # and this request wrote no audit entry


# ==== act: warn ===================================================================================

def test_warn_from_a_user_report_warns_the_reported_user_about_the_profile(db):
    _seed(db, "user")
    res = _act(action="warn")
    _assert_closed_response(db, res, 1, "action_taken", "warned")
    warnings = _warnings(db)
    assert len(warnings) == 1
    w = warnings[0]
    assert (w["user_id"], w["admin_id"], w["reason"]) == (TOM, ADM, REASON)
    assert (w["about_type"], str(w["about_id"])) == ("profile", TOM)
    _assert_closure_audit(db, 1, "report_action_taken", "warned")


def test_warn_from_a_message_report_warns_the_message_author_about_the_message(db):
    _seed(db, "message")
    res = _act(action="warn")
    _assert_closed_response(db, res, 1, "action_taken", "warned")
    warnings = _warnings(db)
    assert [w["user_id"] for w in warnings] == [TOM]
    assert (warnings[0]["about_type"], str(warnings[0]["about_id"])) == ("chat_message", str(MSG))
    assert warnings[0]["reason"] == REASON and warnings[0]["admin_id"] == ADM
    assert _chat_row(db)["removed_at"] is None                      # warning is not a removal
    _assert_closure_audit(db, 1, "report_action_taken", "warned")


def test_warn_from_an_event_report_warns_the_organizer_not_the_reporter_or_participants(db):
    _seed(db, "event")
    res = _act(action="warn")
    _assert_closed_response(db, res, 1, "action_taken", "warned")
    warnings = _warnings(db)
    assert [w["user_id"] for w in warnings] == [TOM]                # TOM organizes EV1; MIA reported, ANA joined
    assert (warnings[0]["about_type"], str(warnings[0]["about_id"])) == ("event", EV1)
    assert warnings[0]["admin_id"] == ADM and warnings[0]["reason"] == REASON
    assert _warnings(db, MIA) == [] and _warnings(db, ANA) == []
    assert _event_row(db)["removed_at"] is None
    _assert_closure_audit(db, 1, "report_action_taken", "warned")


def test_warn_from_an_event_report_follows_the_organizer_of_that_event(db):
    _seed(db, "event", event_id=EV2)                                # EV2 is organized by ANA
    assert _act(action="warn").status_code == 200
    assert [w["user_id"] for w in _warnings(db)] == [ANA]
    assert str(_warnings(db)[0]["about_id"]) == EV2


def test_warn_does_not_suspend_or_remove_anything(db):
    _seed(db, "message")
    assert _act(action="warn").status_code == 200
    assert all(p["suspended_at"] is None for p in db.tables["profiles"])
    assert all(e["removed_at"] is None for e in db.tables["events"])


# ==== act: suspend ================================================================================

@pytest.mark.parametrize("kind", KINDS)
def test_suspend_suspends_the_reported_user_or_the_organizer(db, kind):
    _seed(db, kind)
    res = _act(action="suspend", reason="Harassment in chats")
    _assert_closed_response(db, res, 1, "action_taken", "suspended")
    tom = _profile_row(db, TOM)
    assert tom["suspended_at"] is not None and tom["suspension_reason"] == "Harassment in chats"
    for uid in (MIA, ANA, ADM, ADM2):
        assert _profile_row(db, uid)["suspended_at"] is None, uid
    assert _warnings(db) == []                                      # suspension gives no warning
    _assert_closure_audit(db, 1, "report_action_taken", "suspended")


def test_suspend_from_an_event_report_suspends_the_organizer_not_the_reporter(db):
    _seed(db, "event", event_id=EV2)                                # organizer ANA
    assert _act(action="suspend").status_code == 200
    assert _profile_row(db, ANA)["suspended_at"] is not None
    assert _profile_row(db, MIA)["suspended_at"] is None and _profile_row(db, TOM)["suspended_at"] is None


# ==== act: remove_content =========================================================================

def test_remove_content_from_an_event_report_removes_the_event_and_warns_the_organizer(db):
    _seed(db, "event")
    res = _act(action="remove_content", reason=None)
    _assert_closed_response(db, res, 1, "action_taken", "content_removed")
    ev = _event_row(db)
    assert ev["removed_at"] is not None and ev["removed_by"] == ADM
    assert _event_row(db, EV2)["removed_at"] is None
    warnings = _warnings(db)
    assert [w["user_id"] for w in warnings] == [TOM]
    assert (warnings[0]["about_type"], str(warnings[0]["about_id"])) == ("event", EV1)
    assert warnings[0]["admin_id"] == ADM
    assert _detail()["content_removed"] is True
    # the removal knows which report it came from (the existing report_id parameter)
    removal = [l for l in db.tables["logs"] if l["type"] == "event_removed"]
    assert len(removal) == 1 and "report_id:1" in removal[0]["values"]
    _assert_closure_audit(db, 1, "report_action_taken", "content_removed")


def test_remove_content_from_a_message_report_removes_the_message_and_warns_the_author(db):
    _seed(db, "message")
    res = _act(action="remove_content", reason=None)
    _assert_closed_response(db, res, 1, "action_taken", "content_removed")
    msg = _chat_row(db)
    assert msg["removed_at"] is not None and msg["removed_by"] == ADM
    assert _chat_row(db, OTHER_MSG)["removed_at"] is None
    assert _event_row(db)["removed_at"] is None                      # only the message goes
    warnings = _warnings(db)
    assert [w["user_id"] for w in warnings] == [TOM]
    assert (warnings[0]["about_type"], str(warnings[0]["about_id"])) == ("chat_message", str(MSG))
    removal = [l for l in db.tables["logs"] if l["type"] == "message_removed"]
    assert len(removal) == 1 and "report_id:1" in removal[0]["values"]
    _assert_closure_audit(db, 1, "report_action_taken", "content_removed")


def test_remove_content_ignores_a_reason(db):
    _seed(db, "event")
    res = _act(action="remove_content", reason="not needed here")
    assert res.status_code == 200, res.text
    assert res.json()["outcome"] == "content_removed"


def test_remove_content_on_a_user_report_from_a_profile_is_400_no_content_to_remove(db):
    _seed(db, "user")
    before = _snapshot(db)
    res = _act(action="remove_content", reason=None)
    assert res.status_code == 400, res.text
    assert _code(res) == "no_content_to_remove"
    _assert_untouched(db, before)
    _assert_open_unchanged(db)


def test_remove_content_on_an_already_removed_event_is_409_already_removed(db):
    _seed(db, "event")
    _event_row(db).update(removed_at="2026-10-20T00:00:00+00:00", removed_by=ADM2)
    before = _snapshot(db)
    res = _act(action="remove_content", reason=None)
    assert res.status_code == 409, res.text
    assert _code(res) == "already_removed"
    _assert_untouched(db, before)
    assert _event_row(db)["removed_by"] == ADM2
    _assert_open_unchanged(db)


def test_remove_content_on_an_already_removed_message_is_409_already_removed(db):
    _seed(db, "message")
    _chat_row(db).update(removed_at="2026-10-20T00:00:00+00:00", removed_by=ADM2)
    before = _snapshot(db)
    res = _act(action="remove_content", reason=None)
    assert res.status_code == 409, res.text
    assert _code(res) == "already_removed"
    _assert_untouched(db, before)


def test_remove_content_on_a_hard_deleted_message_is_409_already_removed(db):
    _seed(db, "message")
    db.tables["event_chats"] = [c for c in db.tables["event_chats"] if c["id"] != MSG]
    before = _snapshot(db)
    res = _act(action="remove_content", reason=None)
    assert res.status_code == 409, res.text
    assert _code(res) == "already_removed"
    _assert_untouched(db, before)
    assert _detail()["content_removed"] is True                      # matches the details


def test_remove_content_on_a_deleted_event_with_null_event_id_is_409_already_removed(db):
    _seed(db, "event", event_id=None)
    before = _snapshot(db)
    res = _act(action="remove_content", reason=None)
    assert res.status_code == 409, res.text
    assert _code(res) == "already_removed"
    _assert_untouched(db, before)
    assert _detail()["content_removed"] is True


def test_remove_content_on_an_event_row_that_is_gone_is_409_already_removed(db):
    _seed(db, "event")
    db.tables["events"] = [e for e in db.tables["events"] if e["id"] != EV1]
    before = _snapshot(db)
    res = _act(action="remove_content", reason=None)
    assert res.status_code == 409, res.text
    assert _code(res) == "already_removed"
    _assert_untouched(db, before)


@pytest.mark.parametrize("kind", ["event", "message"])
def test_remove_content_when_the_owner_is_an_administrator_removes_without_a_warning(db, kind):
    _seed(db, kind)
    _make_admin(db)                                                  # TOM is now an administrator
    res = _act(action="remove_content", reason=None)
    _assert_closed_response(db, res, 1, "action_taken", "content_removed")
    if kind == "event":
        assert _event_row(db)["removed_at"] is not None
    else:
        assert _chat_row(db)["removed_at"] is not None
    assert _warnings(db) == []                                       # no warning for an administrator
    _assert_closure_audit(db, 1, "report_action_taken", "content_removed")


# ==== act: refusals ===============================================================================

@pytest.mark.parametrize("action", ["warn", "suspend"])
@pytest.mark.parametrize("kind", KINDS)
def test_warn_or_suspend_when_the_target_is_now_an_administrator_is_400(db, kind, action):
    _seed(db, kind)
    _make_admin(db)                                                  # reported user / author / organizer
    before = _snapshot(db)
    res = _act(action=action)
    assert res.status_code == 400, res.text
    assert _code(res) == "reported_user_is_administrator"
    _assert_untouched(db, before)
    _assert_open_unchanged(db)
    assert _warnings(db) == [] and _profile_row(db, TOM)["suspended_at"] is None
    assert _detail()["reported_user_is_administrator"] is True


@pytest.mark.parametrize("kind", KINDS)
def test_suspend_an_already_suspended_account_is_409_already_suspended(db, kind):
    _seed(db, kind)
    _profile_row(db, TOM).update(suspended_at="2026-10-15T00:00:00+00:00", suspension_reason="earlier")
    before = _snapshot(db)
    res = _act(action="suspend")
    assert res.status_code == 409, res.text
    assert _code(res) == "already_suspended"
    _assert_untouched(db, before)
    _assert_open_unchanged(db)
    assert _profile_row(db, TOM)["suspension_reason"] == "earlier"


GONE = [("user", "profile_deleted"), ("user", "null_id"),
        ("message", "profile_deleted"), ("message", "null_id"),
        ("event", "profile_deleted"), ("event", "created_by_null"), ("event", "deleted_event")]


def _make_gone(db, how):
    if how == "profile_deleted":
        db.tables["profiles"] = [p for p in db.tables["profiles"] if p["id"] != TOM]
    elif how == "null_id":
        _row(db)["reported_user_id"] = None
    elif how == "created_by_null":
        _event_row(db)["created_by"] = None
    else:
        _row(db)["event_id"] = None


@pytest.mark.parametrize("action", ["warn", "suspend"])
@pytest.mark.parametrize("kind,how", GONE)
def test_warn_or_suspend_when_the_reported_user_is_gone_is_404_reported_user_not_found(db, kind, how, action):
    _seed(db, kind)
    _make_gone(db, how)
    before = _snapshot(db)
    res = _act(action=action)
    assert res.status_code == 404, res.text
    assert _code(res) == "reported_user_not_found"
    _assert_untouched(db, before)
    _assert_open_unchanged(db)


def test_unknown_report_on_act_is_404_report_not_found(db):
    _seed(db, "event")
    before = _snapshot(db)
    res = _act(rid=999, action="warn")
    assert res.status_code == 404, res.text
    assert _code(res) == "report_not_found"
    _assert_untouched(db, before)


@pytest.mark.parametrize("action", ["warn", "suspend", "remove_content"])
@pytest.mark.parametrize("closed", [
    {"status": "dismissed", "outcome": "dismissed"},
    {"status": "action_taken", "outcome": "warned"},
])
def test_act_on_a_closed_report_is_409_report_closed(db, closed, action):
    _seed(db, "message", closed_by=ADM2, closed_at=OLD_CLOSE, **closed)
    before = _snapshot(db)
    res = _act(action=action)
    assert res.status_code == 409, res.text
    assert _code(res) == "report_closed"
    _assert_untouched(db, before)


@pytest.mark.parametrize("action", ["warn", "suspend"])
def test_closed_report_with_an_administrator_target_still_answers_report_closed_not_400(db, action):
    _seed(db, "user", status="dismissed", outcome="dismissed", closed_by=ADM2, closed_at=OLD_CLOSE)
    _make_admin(db)
    res = _act(action=action)
    assert res.status_code == 409, res.text
    assert _code(res) == "report_closed"


def test_closed_report_precedes_already_removed_and_no_content_to_remove(db):
    _seed(db, "message", 1, status="dismissed", outcome="dismissed", closed_by=ADM2, closed_at=OLD_CLOSE)
    _seed(db, "user", 2, status="dismissed", outcome="dismissed", closed_by=ADM2, closed_at=OLD_CLOSE)
    _chat_row(db)["removed_at"] = "2026-10-20T00:00:00+00:00"
    for rid in (1, 2):
        res = _act(rid=rid, action="remove_content", reason=None)
        assert res.status_code == 409 and _code(res) == "report_closed", (rid, res.text)


@pytest.mark.parametrize("action", ["warn", "suspend"])
def test_closed_report_precedes_reported_user_not_found(db, action):
    _seed(db, "user", status="action_taken", outcome="warned", closed_by=ADM2, closed_at=OLD_CLOSE)
    _make_gone(db, "profile_deleted")
    res = _act(action=action)
    assert res.status_code == 409 and _code(res) == "report_closed"


def test_act_conflict_when_another_admin_closes_it_first_runs_no_service(db, race):
    _seed(db, "message")
    res = _act(action="warn")
    assert race.fired, "the claim never touched the reports table"
    assert res.status_code == 409, res.text
    assert _warnings(db) == []
    assert _row(db)["closed_by"] == ADM2 and _row(db)["outcome"] == "dismissed"
    assert _report_logs(db) == []


# ==== act: request validation =====================================================================

@pytest.mark.parametrize("action", ["warn", "suspend"])
@pytest.mark.parametrize("reason", [None, "", "   ", "\n\t", "x" * (WARNING_REASON_MAX_LENGTH + 1)],
                         ids=["missing", "empty", "blank", "whitespace", "too_long"])
def test_warn_and_suspend_need_a_valid_reason_422(db, action, reason):
    assert WARNING_REASON_MAX_LENGTH == SUSPENSION_REASON_MAX_LENGTH == 1000
    _seed(db, "message")
    before = _snapshot(db)
    res = _act(action=action, reason=reason)
    assert res.status_code == 422, res.text
    _assert_untouched(db, before)
    assert _warnings(db) == [] and _profile_row(db, TOM)["suspended_at"] is None
    _assert_open_unchanged(db)


@pytest.mark.parametrize("action", ["warn", "suspend"])
def test_null_or_non_string_reason_is_422(db, action):
    _seed(db, "message")
    for bad in (None, 5, ["a"]):
        res = client.post("/api/admin/reports/1/action", json={"action": action, "reason": bad})
        assert res.status_code == 422, (bad, res.text)
    _assert_open_unchanged(db)


@pytest.mark.parametrize("action", ["warn", "suspend"])
def test_reason_of_exactly_the_limit_is_accepted(db, action):
    _seed(db, "message")
    res = _act(action=action, reason="y" * WARNING_REASON_MAX_LENGTH)
    assert res.status_code == 200, res.text


@pytest.mark.parametrize("action", ["warn", "suspend"])
def test_reason_with_surrounding_spaces_is_accepted(db, action):
    _seed(db, "message")
    res = _act(action=action, reason=f"  {REASON}  ")
    assert res.status_code == 200, res.text


def test_remove_content_does_not_need_a_reason(db):
    _seed(db, "event")
    res = client.post("/api/admin/reports/1/action", json={"action": "remove_content"})
    assert res.status_code == 200, res.text


@pytest.mark.parametrize("payload", [
    {"action": "ban", "reason": REASON},
    {"action": "", "reason": REASON},
    {"action": "dismiss", "reason": REASON},
    {"action": "WARN", "reason": REASON},
    {"action": None, "reason": REASON},
    {"reason": REASON},
    {},
], ids=["ban", "empty", "dismiss", "uppercase", "null", "missing_action", "empty_body"])
def test_invalid_action_is_422(db, payload):
    _seed(db, "message")
    before = _snapshot(db)
    res = client.post("/api/admin/reports/1/action", json=payload)
    assert res.status_code == 422, res.text
    _assert_untouched(db, before)


def test_action_without_a_body_is_422(db):
    _seed(db, "message")
    assert client.post("/api/admin/reports/1/action").status_code == 422
    _assert_open_unchanged(db)


def test_non_numeric_report_id_is_422(db):
    assert client.post("/api/admin/reports/abc/dismiss").status_code == 422
    assert client.post("/api/admin/reports/abc/action", json={"action": "warn", "reason": REASON}).status_code == 422


# ==== a closed report accepts no further action ===================================================

FIRST_THEN_SECOND = [
    ("dismiss", "dismiss"), ("dismiss", "warn"), ("dismiss", "suspend"), ("dismiss", "remove_content"),
    ("warn", "dismiss"), ("warn", "warn"), ("warn", "suspend"), ("warn", "remove_content"),
    ("suspend", "dismiss"), ("suspend", "warn"), ("suspend", "suspend"), ("suspend", "remove_content"),
    ("remove_content", "dismiss"), ("remove_content", "warn"), ("remove_content", "suspend"),
    ("remove_content", "remove_content"),
]


def _do(what):
    return _dismiss() if what == "dismiss" else _act(action=what, reason=None if what == "remove_content" else REASON)


@pytest.mark.parametrize("first,second", FIRST_THEN_SECOND)
def test_a_second_request_after_a_success_is_409_report_closed_and_runs_no_service(db, first, second):
    _seed(db, "message")
    assert _do(first).status_code == 200
    after_first = _snapshot(db)
    res = _do(second)
    assert res.status_code == 409, res.text
    assert _code(res) == "report_closed"
    _assert_untouched(db, after_first)           # no second warning, suspension, removal, audit entry or write
    assert len(_report_logs(db)) == 1


def test_the_second_warn_does_not_create_a_second_warning(db):
    _seed(db, "event")
    assert _act(action="warn").status_code == 200
    assert _act(action="warn").status_code == 409
    assert len(_warnings(db)) == 1


# ==== failure after the claim =====================================================================

def _assert_reverted(db):
    _assert_open_unchanged(db)
    assert _report_logs(db) == []


def test_warn_failing_after_the_claim_reverts_it_and_returns_the_original_error(db, fail):
    _seed(db, "message")
    fail.arm(_warnings_insert, HTTPException(status_code=503, detail="warnings are down"))
    res = _act(action="warn")
    assert fail.hits >= 1, "the warning insert was never reached"
    assert res.status_code == 503, res.text
    _assert_reverted(db)
    assert _warnings(db) == []
    # the report really is open again: a retry works
    fail.disarm()
    res = _act(action="warn")
    _assert_closed_response(db, res, 1, "action_taken", "warned")
    assert len(_warnings(db)) == 1


def test_suspend_failing_after_the_claim_reverts_it_and_returns_the_original_error(db, fail):
    _seed(db, "user")
    fail.arm(_profiles_update, HTTPException(status_code=503, detail="profiles are down"))
    res = _act(action="suspend")
    assert fail.hits >= 1, "the suspension update was never reached"
    assert res.status_code == 503, res.text
    _assert_reverted(db)
    assert _profile_row(db, TOM)["suspended_at"] is None
    fail.disarm()
    assert _act(action="suspend").status_code == 200
    assert _profile_row(db, TOM)["suspended_at"] is not None


def test_remove_event_failing_on_the_warning_returns_removal_failed_and_reverts_the_claim(db, fail):
    _seed(db, "event")
    fail.arm(_warnings_insert, RuntimeError("warnings are down"))
    res = _act(action="remove_content", reason=None)
    assert fail.hits >= 1, "the removal warning insert was never reached"
    assert res.status_code == 500, res.text
    assert _code(res) == "removal_failed"          # the removal service's own error, passed through
    _assert_reverted(db)
    ev = _event_row(db)
    assert ev["removed_at"] is None and ev["removed_by"] is None     # the removal undid itself
    assert _warnings(db) == []
    fail.disarm()
    assert _act(action="remove_content", reason=None).status_code == 200


def test_remove_message_failing_on_the_warning_returns_removal_failed_and_reverts_the_claim(db, fail):
    _seed(db, "message")
    fail.arm(_warnings_insert, RuntimeError("warnings are down"))
    res = _act(action="remove_content", reason=None)
    assert fail.hits >= 1
    assert res.status_code == 500, res.text
    assert _code(res) == "removal_failed"
    _assert_reverted(db)
    assert _chat_row(db)["removed_at"] is None and _chat_row(db)["removed_by"] is None


def test_remove_event_failing_on_the_removal_update_reverts_the_claim(db, fail):
    _seed(db, "event")
    fail.arm(_event_removal_update, HTTPException(status_code=503, detail="events are down"))
    res = _act(action="remove_content", reason=None)
    assert fail.hits >= 1
    assert res.status_code == 503, res.text
    _assert_reverted(db)
    assert _event_row(db)["removed_at"] is None
    assert _warnings(db) == []


def test_unexpected_error_in_the_service_still_reverts_the_claim(db, fail):
    _seed(db, "event")
    fail.arm(_warnings_insert, RuntimeError("boom"))
    res = TestClient(app, raise_server_exceptions=False).post(
        "/api/admin/reports/1/action", json={"action": "warn", "reason": REASON})
    assert fail.hits >= 1
    assert res.status_code == 500, res.text
    _assert_reverted(db)


# ==== GET details after each outcome ==================================================================

@pytest.mark.parametrize("kind,action", COMBOS)
def test_details_show_outcome_closer_and_time_after_each_outcome(db, kind, action):
    _seed(db, kind)
    res = _do(action)
    assert res.status_code == 200, res.text
    body = _detail()
    assert body["status"] == "action_taken" and body["outcome"] == ACTION_OUTCOME[action]
    assert body["closed_by"]["id"] == ADM and body["closed_by"]["username"] == "boss"
    assert body["closed_at"] == str(_row(db)["closed_at"])


def test_details_after_dismiss_and_the_lists_show_the_closure(db):
    _seed(db, "event", 1)
    _seed(db, "event", 2)
    assert _dismiss(1).status_code == 200
    body = _detail(1)
    assert (body["status"], body["outcome"], body["closed_by"]["id"]) == ("dismissed", "dismissed", ADM)
    open_ids = [i["id"] for i in client.get("/api/admin/reports/open").json()["items"]]
    assert open_ids == [2]
    all_items = {i["id"]: i["status"] for i in client.get("/api/admin/reports").json()["items"]}
    assert all_items == {1: "dismissed", 2: "open"}


def test_closing_one_report_leaves_other_open_reports_alone(db):
    _seed(db, "message", 1)
    _seed(db, "message", 2)                                          # a second report about the same message
    assert _act(1, action="warn").status_code == 200
    _assert_open_unchanged(db, 2)
    assert len(_warnings(db)) == 1


# ==== audit ===========================================================================================

def test_a_refused_request_writes_no_report_audit_entry(db):
    _seed(db, "user")
    assert _act(action="remove_content", reason=None).status_code == 400
    assert _dismiss(999).status_code == 404
    assert _report_logs(db) == []


def test_warn_still_writes_its_own_warning_audit_entry_next_to_the_report_one(db):
    _seed(db, "user")
    assert _act(action="warn").status_code == 200
    types = sorted(l["type"] for l in db.tables["logs"])
    assert "report_action_taken" in types and "warning_given" in types
    assert len(_report_logs(db)) == 1                                # exactly one report-level entry


# ==== admin only: the REAL require_admin chain (like tests/test_admin_reports_read.py) ================

def _jwt(payload):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{enc({'alg': 'HS256'})}.{enc(payload)}.sig"


def _real_chain(mock_sb, role, aal):
    """Real require_admin: only Supabase auth and the role lookup (app.core.dependencies) are mocked."""
    app.dependency_overrides.clear()
    mock_sb.auth.get_user.return_value = MagicMock(user=SimpleNamespace(id=ADM))
    chain = MagicMock()
    chain.select.return_value = chain.eq.return_value = chain.single.return_value = chain
    chain.execute.return_value = MagicMock(data={"role": role})
    mock_sb.table.return_value = chain
    return {"Authorization": f"Bearer {_jwt({'sub': ADM, 'aal': aal})}"}


ACTION_BODY = {"action": "warn", "reason": REASON}
POST_ENDPOINTS = [
    ("/api/admin/reports/1/dismiss", None),
    ("/api/admin/reports/1/dismiss/", None),
    ("/api/admin/reports/1/action", ACTION_BODY),
    ("/api/admin/reports/1/action/", ACTION_BODY),
]
POST_IDS = ["dismiss", "dismiss_slash", "action", "action_slash"]


def _post(url, body, headers=None):
    # follow_redirects=False: a redirect would drop the MFA token, so it must not be needed
    return client.post(url, json=body, headers=headers or {}, follow_redirects=False)


@pytest.mark.parametrize("url,body", POST_ENDPOINTS, ids=POST_IDS)
@patch("app.core.dependencies.supabase")
def test_real_chain_user_role_gets_403_even_with_mfa(mock_sb, db, url, body):
    _seed(db, "event")
    headers = _real_chain(mock_sb, "user", "aal2")
    before = _snapshot(db)
    res = _post(url, body, headers)
    assert res.status_code == 403, f"{url}: {res.status_code} {res.text}"
    _assert_untouched(db, before)


@pytest.mark.parametrize("url,body", POST_ENDPOINTS, ids=POST_IDS)
@patch("app.core.dependencies.supabase")
def test_real_chain_administrator_without_mfa_gets_403(mock_sb, db, url, body):
    _seed(db, "event")
    headers = _real_chain(mock_sb, "administrator", "aal1")
    before = _snapshot(db)
    res = _post(url, body, headers)
    assert res.status_code == 403, f"{url}: {res.status_code} {res.text}"
    assert "MFA" in res.json()["detail"]
    _assert_untouched(db, before)


@pytest.mark.parametrize("url,body", POST_ENDPOINTS, ids=POST_IDS)
@patch("app.core.dependencies.supabase")
def test_real_chain_administrator_with_mfa_succeeds_without_a_redirect(mock_sb, db, url, body):
    _seed(db, "event")
    headers = _real_chain(mock_sb, "administrator", "aal2")
    res = _post(url, body, headers)
    assert res.status_code == 200, f"{url}: {res.status_code} {res.text}"
    assert res.json()["status"] in ("dismissed", "action_taken")
    assert res.json()["closed_by"]["id"] == ADM
    assert _row(db)["closed_by"] == ADM


@pytest.mark.parametrize("url,body", POST_ENDPOINTS, ids=POST_IDS)
def test_unauthenticated_post_is_refused_like_other_admin_endpoints(db, url, body):
    app.dependency_overrides.clear()
    _seed(db, "event")
    baseline = client.get("/api/admin/users", follow_redirects=False).status_code
    assert baseline in (401, 403)
    before = _snapshot(db)
    res = _post(url, body)
    assert res.status_code in (401, 403)
    assert res.status_code == baseline, f"POST {url} returned {res.status_code}, other admin endpoints {baseline}"
    _assert_untouched(db, before)


@pytest.mark.parametrize("url,body", POST_ENDPOINTS, ids=POST_IDS)
@patch("app.core.dependencies.supabase")
def test_real_chain_refusal_comes_before_report_lookup(mock_sb, db, url, body):
    """A non-administrator learns nothing about whether the report exists (403, not 404)."""
    headers = _real_chain(mock_sb, "user", "aal2")
    res = _post(url.replace("/1/", "/999/"), body, headers)
    assert res.status_code == 403, f"{url}: {res.status_code} {res.text}"
