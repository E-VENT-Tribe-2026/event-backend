"""Ticket #235 phase 3, failure paths of dismiss / act on a report.

The reused warning, suspension and removal services are not atomic, so a request can fail in the
middle. These tests pin what the report endpoints do then (same world and helpers as
tests/test_admin_reports_actions.py, the REAL services against the in-memory Supabase fake):

  * a failure AFTER the service's work was committed keeps the report closed and answers 200
    (a retry would warn / remove twice, or be stuck on 409 already_removed);
  * a failure BEFORE it reopens the report and raises the original error;
  * a reopen that fails is retried, then logged CRITICAL + audited ("report_close_unreverted");
  * a reopen never touches a closure of another administrator;
  * a failing details load never turns a success into a 500 (second try, then a fallback body);
  * a race between the validation and the service gives the coded refusals;
  * the 422 for a bad reason points at body.reason.

Every injected failure asserts that it was really hit, so no test passes vacuously.
"""
import logging
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.admin_report_schema import AdminReportDetailResponse
from app.schemas.warning_schema import WARNING_REASON_MAX_LENGTH
from tests import _fake_supabase
from tests.test_admin_reports_actions import (  # noqa: F401  (db and race are fixtures)
    ADM, ADM2, ANA, DETAIL_KEYS, EV1, MIA, MSG, OLD_CLOSE, REASON, TOM,
    _act, _assert_closed_response, _assert_open_unchanged, _assert_reverted, _chat_row, _code, _detail,
    _dismiss, _event_row, _profile_row, _report_logs, _row, _seed, _warnings, client, db, race,
)

server_errors = TestClient(app, raise_server_exceptions=False)


# ---- failure injection ----------------------------------------------------------------------------

@pytest.fixture
def inject(monkeypatch):
    """inject(when, error=None, skip=0, times=1, after=False, effect=None) -> rule with .hits

    The first `skip` matching queries pass untouched, then up to `times` (None = always) are hit:
    effect(query) runs first, then `error` is raised instead of running the query (after=True: the query
    is applied first and the error is raised afterwards, like a lost response). Without an error the rule
    only counts / has an effect."""
    rules = []
    original = _fake_supabase.FakeQuery.execute

    def execute(self):
        for rule in rules:
            if not rule.when(self):
                continue
            rule.seen += 1
            if rule.seen <= rule.skip or (rule.times is not None and rule.hits >= rule.times):
                continue
            rule.hits += 1
            if rule.effect:
                rule.effect(self)
            if rule.error is not None:
                if rule.after:
                    original(self)
                raise rule.error
            break
        return original(self)

    monkeypatch.setattr(_fake_supabase.FakeQuery, "execute", execute)

    def add(when, error=None, skip=0, times=1, after=False, effect=None):
        rule = SimpleNamespace(when=when, error=error, skip=skip, times=times, after=after, effect=effect,
                               seen=0, hits=0)
        rules.append(rule)
        return rule

    return add


def _payload(q):
    return q.payload or {}


def _warnings_insert(q):
    return q.name == "warnings" and q.action == "insert"


def _warnings_select(q):
    return q.name == "warnings" and q.action == "select"


def _people_select(q):
    """audit_service._people: the profiles lookup that selects the username."""
    return q.name == "profiles" and q.action == "select" and "username" in q.cols


def _profiles_select(q):
    return q.name == "profiles" and q.action == "select"


def _events_select(q):
    return q.name == "events" and q.action == "select"


def _chat_removal_update(q):
    return q.name == "event_chats" and q.action == "update" and "removed_at" in _payload(q)


def _reports_claim(q):
    return q.name == "reports" and q.action == "update" and _payload(q).get("status") != "open"


def _reports_reopen(q):
    return q.name == "reports" and q.action == "update" and _payload(q).get("status") == "open"


def _reports_update(q):
    return q.name == "reports" and q.action == "update"


def _reports_details_read(q):
    return q.name == "reports" and q.action == "select" and q.cols == "*"


def _notifications(db, type_=None, user=None):
    return [n for n in db.tables["notifications"]
            if (type_ is None or n["type"] == type_) and (user is None or n["user_id"] == user)]


def _logged(caplog, level, text):
    return [r for r in caplog.records if r.levelno == level and text in r.getMessage()]


def _audit_types(db):
    return sorted(l["type"] for l in db.tables["logs"])


# ==== F-001: the service raised after its work was committed ==========================================

def test_warn_failing_in_the_last_lookup_keeps_the_report_closed_and_does_not_warn_twice(db, inject, caplog):
    _seed(db, "message")
    # give_warning ends with _people([admin]) after the warning, notification and audit entry exist
    lookup = inject(_people_select, RuntimeError("profiles went away"))
    with caplog.at_level(logging.INFO):
        res = _act(action="warn")
    assert lookup.hits == 1, "the failure was never injected"
    _assert_closed_response(db, res, 1, "action_taken", "warned")
    assert len(_warnings(db)) == 1 and len(_notifications(db, "warning", TOM)) == 1
    assert _audit_types(db).count("warning_given") == 1
    logs = _report_logs(db)
    assert [l["type"] for l in logs] == ["report_action_taken"]
    assert _logged(caplog, logging.ERROR, "the action was done but the service raised afterwards")
    assert any(r.exc_info and "profiles went away" in str(r.exc_info[1]) for r in caplog.records)  # original

    retry = _act(action="warn")                       # the report really is closed
    assert retry.status_code == 409 and _code(retry) == "report_closed"
    assert len(_warnings(db)) == 1 and len(_notifications(db, "warning", TOM)) == 1


def test_remove_event_failing_in_the_result_after_the_removal_keeps_the_report_closed(db, inject, caplog):
    _seed(db, "event")                                # EV1 is upcoming (2099), MIA and ANA joined, TOM organizes
    lookup = inject(_people_select, RuntimeError("profiles went away"))
    with caplog.at_level(logging.INFO):
        res = _act(action="remove_content", reason=None)
    assert lookup.hits == 1, "the failure was never injected"
    _assert_closed_response(db, res, 1, "action_taken", "content_removed")
    ev = _event_row(db)
    assert ev["removed_at"] is not None and ev["removed_by"] == ADM
    assert _detail()["content_removed"] is True
    # the queued BackgroundTask still ran: the participants (not the organizer) were told
    told = sorted(n["user_id"] for n in _notifications(db, "event_removed"))
    assert told == sorted([MIA, ANA])
    assert len(_notifications(db, "content_removed", TOM)) == 1
    assert _logged(caplog, logging.ERROR, "the action was done but the service raised afterwards")
    assert [l["type"] for l in _report_logs(db)] == ["report_action_taken"]

    retry = _act(action="remove_content", reason=None)
    assert retry.status_code == 409 and _code(retry) == "report_closed"
    assert len(_notifications(db, "event_removed")) == 2 and len(_warnings(db)) == 1


def test_remove_message_failing_between_the_mark_and_the_warning_keeps_the_report_closed(db, inject, caplog):
    _seed(db, "message")
    lookup = inject(_events_select, RuntimeError("events went away"))     # remove_message's unguarded read
    with caplog.at_level(logging.INFO):
        res = _act(action="remove_content", reason=None)
    assert lookup.hits == 1, "the failure was never injected"
    _assert_closed_response(db, res, 1, "action_taken", "content_removed")
    msg = _chat_row(db)
    assert msg["removed_at"] is not None and msg["removed_by"] == ADM     # the removal stands
    assert _logged(caplog, logging.ERROR, "the action was done but the service raised afterwards")
    retry = _act(action="remove_content", reason=None)
    assert retry.status_code == 409 and _code(retry) == "report_closed"


def test_remove_message_failing_before_the_mark_still_reverts_the_claim(db, inject):
    _seed(db, "message")
    mark = inject(_chat_removal_update, HTTPException(status_code=503, detail="chats are down"))
    res = _act(action="remove_content", reason=None)
    assert mark.hits == 1, "the failure was never injected"
    assert res.status_code == 503, res.text
    _assert_reverted(db)
    assert _chat_row(db)["removed_at"] is None
    assert _act(action="remove_content", reason=None).status_code == 200


def test_a_warning_older_than_the_claim_is_not_the_effect_of_this_request(db, inject):
    """An earlier warning of the same administrator for the same item must not count as done."""
    _seed(db, "message")
    db.tables["warnings"].append({"id": 900, "user_id": TOM, "admin_id": ADM, "reason": "earlier",
                                  "about_type": "chat_message", "about_id": str(MSG),
                                  "created_at": "2026-01-01T00:00:00+00:00"})
    insert = inject(_warnings_insert, HTTPException(status_code=503, detail="warnings are down"))
    res = _act(action="warn")
    assert insert.hits == 1
    assert res.status_code == 503, res.text
    _assert_reverted(db)
    assert [w["id"] for w in _warnings(db)] == [900]


def test_a_warning_by_another_admin_is_not_the_effect_of_this_request(db, inject):
    _seed(db, "message")
    db.tables["warnings"].append({"id": 900, "user_id": TOM, "admin_id": ADM2, "reason": "other admin",
                                  "about_type": "chat_message", "about_id": str(MSG),
                                  "created_at": "2099-01-01T00:00:00+00:00"})
    insert = inject(_warnings_insert, HTTPException(status_code=503, detail="warnings are down"))
    res = _act(action="warn")
    assert insert.hits == 1
    assert res.status_code == 503, res.text
    _assert_reverted(db)


def test_when_the_effect_cannot_be_checked_the_report_stays_closed_and_is_flagged(db, inject, caplog):
    """Unknown outcome: reopening could repeat a committed action, so keep it closed, raise the original
    error, and leave a CRITICAL log + audit entry for a human."""
    _seed(db, "message")
    service = inject(_warnings_insert, HTTPException(status_code=503, detail="warnings are down"))
    check = inject(_warnings_select, RuntimeError("cannot look"))
    with caplog.at_level(logging.INFO):
        res = _act(action="warn")
    assert service.hits == 1 and check.hits >= 1
    assert res.status_code == 503, res.text                       # the original error
    row = _row(db)
    assert (row["status"], row["closed_by"]) == ("action_taken", ADM)
    assert _logged(caplog, logging.CRITICAL, "Report 1 ")
    logs = _report_logs(db)
    assert [l["type"] for l in logs] == ["report_close_unreverted"]
    assert "effect:unknown" in logs[0]["values"]
    assert _act(action="warn").status_code == 409                 # nothing can be repeated


# ==== F-002: reopening ================================================================================

def test_failed_service_and_a_reopen_that_always_fails_is_flagged_critical_and_audited(db, inject, caplog):
    _seed(db, "message")
    service = inject(_warnings_insert, HTTPException(status_code=503, detail="warnings are down"))
    reopen = inject(_reports_reopen, RuntimeError("reports are down"), times=None)
    with caplog.at_level(logging.INFO):
        res = _act(action="warn")
    assert service.hits == 1
    assert reopen.hits == 3, "the reopen must be tried three times"
    assert res.status_code == 503, res.text                       # still the ORIGINAL error
    critical = _logged(caplog, logging.CRITICAL, "Report 1 ")
    assert critical and critical[0].exc_info
    row = _row(db)
    assert (row["status"], row["outcome"], row["closed_by"]) == ("action_taken", "warned", ADM)
    logs = _report_logs(db)
    assert [l["type"] for l in logs] == ["report_close_unreverted"]
    assert logs[0]["entity_id"] == "1" and logs[0]["created_by_id"] == ADM
    assert "outcome:warned" in logs[0]["values"]
    assert "action:warn" in logs[0]["values"]
    assert _warnings(db) == []


def test_a_reopen_that_hits_the_unique_index_is_retried_then_flagged(db, inject, caplog):
    """The open-report unique index can refuse reopening: a database error, not an unhandled exception."""
    _seed(db, "message")
    inject(_warnings_insert, HTTPException(status_code=503, detail="warnings are down"))
    violation = Exception('duplicate key value violates unique constraint "reports_open_message_uniq" (23505)')
    reopen = inject(_reports_reopen, violation, times=None)
    with caplog.at_level(logging.INFO):
        res = server_errors.post("/api/admin/reports/1/action", json={"action": "warn", "reason": REASON})
    assert reopen.hits == 3
    assert res.status_code == 503, res.text
    assert _logged(caplog, logging.CRITICAL, "Report 1 ")
    assert [l["type"] for l in _report_logs(db)] == ["report_close_unreverted"]


def test_a_reopen_that_fails_once_and_then_works_reopens_the_report(db, inject, caplog):
    _seed(db, "message")
    service = inject(_warnings_insert, HTTPException(status_code=503, detail="warnings are down"))
    reopen = inject(_reports_reopen, RuntimeError("blip"), times=1)
    with caplog.at_level(logging.INFO):
        res = _act(action="warn")
    assert service.hits == 1 and reopen.hits == 1
    assert res.status_code == 503, res.text
    _assert_reverted(db)
    assert not _logged(caplog, logging.CRITICAL, "Report 1 ")


@pytest.mark.parametrize("what", ["dismiss", "warn"])
def test_a_claim_that_raises_after_the_server_applied_it_is_reopened(db, inject, what):
    _seed(db, "message")
    claim = inject(_reports_claim, RuntimeError("response lost"), after=True)
    if what == "dismiss":
        res = server_errors.post("/api/admin/reports/1/dismiss")
    else:
        res = server_errors.post("/api/admin/reports/1/action", json={"action": "warn", "reason": REASON})
    assert claim.hits == 1, "the failure was never injected"
    assert res.status_code == 500, res.text
    _assert_reverted(db)                  # the update WAS applied, the guarded revert reopened it
    assert _warnings(db) == []


def test_a_lost_claim_race_does_not_revert_and_leaves_the_other_closure(db, race, inject):
    _seed(db, "message")
    updates = []
    spy = inject(_reports_update, times=None, effect=lambda q: updates.append(dict(_payload(q))))
    res = _act(action="warn")
    assert race.fired, "the claim never touched the reports table"
    assert res.status_code == 409 and _code(res) == "report_closed"
    assert spy.hits == 1 and len(updates) == 1 and updates[0]["status"] == "action_taken"   # the claim only
    row = _row(db)
    assert (row["status"], row["outcome"], row["closed_by"], row["closed_at"]) == \
           ("dismissed", "dismissed", ADM2, OLD_CLOSE)
    assert _warnings(db) == [] and _report_logs(db) == []


def test_the_revert_never_reopens_a_closure_of_another_administrator(db, inject, caplog):
    """The service fails and, meanwhile, ADM2 took over the closure: the revert must leave it alone."""
    _seed(db, "message")

    def another_admin_closes(_query):
        _row(db).update(closed_by=ADM2, closed_at=OLD_CLOSE)

    service = inject(_warnings_insert, HTTPException(status_code=503, detail="warnings are down"),
                     effect=another_admin_closes)
    with caplog.at_level(logging.INFO):
        res = _act(action="warn")
    assert service.hits == 1
    assert res.status_code == 503, res.text
    row = _row(db)
    assert (row["status"], row["outcome"], row["closed_by"], row["closed_at"]) == \
           ("action_taken", "warned", ADM2, OLD_CLOSE)
    assert not _logged(caplog, logging.CRITICAL, "Report 1 ")


# ==== F-003: details failing after a successful action ================================================

def _fallback_checks(db, res, status, outcome, content_removed):
    assert res.status_code == 200, res.text
    body = res.json()
    parsed = AdminReportDetailResponse.model_validate(body)             # the route's response model
    assert DETAIL_KEYS <= set(body)
    row = _row(db)
    assert (parsed.status, parsed.outcome) == (status, outcome)
    assert (row["status"], row["outcome"], row["closed_by"]) == (status, outcome, ADM)
    assert parsed.closed_by.id == ADM
    assert parsed.closed_at == row["closed_at"]                         # the claim's timestamp
    assert parsed.id == 1 and parsed.reason == row["reason"] and parsed.created_at == str(row["created_at"])
    assert parsed.target_type == row["target_type"] and parsed.origin == row["origin"]
    assert parsed.reporter.id == MIA
    assert parsed.content_removed is content_removed
    assert parsed.reported_user_is_administrator is False
    return parsed


@pytest.mark.parametrize("what", ["dismiss", "warn"])
def test_details_failing_once_are_retried_and_the_normal_body_is_returned(db, inject, what):
    _seed(db, "message")
    load = inject(_reports_details_read, RuntimeError("blip"), skip=1, times=1)
    res = _dismiss() if what == "dismiss" else _act(action="warn")
    assert load.hits == 1, "the failure was never injected"
    status, outcome = ("dismissed", "dismissed") if what == "dismiss" else ("action_taken", "warned")
    _assert_closed_response(db, res, 1, status, outcome)                # the full live body, like GET


@pytest.mark.parametrize("kind,action", [("message", "warn"), ("user", "suspend"), ("event", "warn"),
                                         ("event", "remove_content"), ("message", "remove_content")])
def test_details_failing_every_time_still_answers_200_with_a_fallback_body(db, inject, caplog, kind, action):
    _seed(db, kind)
    load = inject(_reports_details_read, RuntimeError("reports unreadable"), skip=1, times=None)
    with caplog.at_level(logging.INFO):
        res = _act(action=action, reason=None if action == "remove_content" else REASON)
    assert load.hits == 2, "the details must be tried twice"
    removed = action == "remove_content"
    body = _fallback_checks(db, res, "action_taken", {"warn": "warned", "suspend": "suspended",
                                                       "remove_content": "content_removed"}[action], removed)
    assert len(_logged(caplog, logging.ERROR, "Could not load the details of report 1")) == 2
    row = _row(db)
    if kind == "message":                                               # stored as is for a chat report
        assert body.event.id == EV1 and body.chat_context == row["chat_context"]
        assert body.reported.message.id == MSG
    else:
        assert body.event is None and body.chat_context is None
    if kind == "user":
        assert body.reported.user.id == TOM
    if kind == "event":
        assert body.reported.event.id == EV1
    # the action itself happened
    if action == "warn":
        assert len(_warnings(db)) == 1
    elif action == "suspend":
        assert _profile_row(db, TOM)["suspended_at"] is not None
    else:
        assert (_event_row(db) if kind == "event" else _chat_row(db))["removed_by"] == ADM
    assert [l["type"] for l in _report_logs(db)] == ["report_action_taken"]


def test_dismiss_with_details_failing_every_time_answers_200_with_a_fallback_body(db, inject):
    _seed(db, "event")
    load = inject(_reports_details_read, RuntimeError("reports unreadable"), skip=1, times=None)
    res = _dismiss()
    assert load.hits == 2
    _fallback_checks(db, res, "dismissed", "dismissed", False)
    assert [l["type"] for l in _report_logs(db)] == ["report_dismissed"]


def test_the_participants_are_still_notified_when_the_details_fail(db, inject):
    _seed(db, "event")
    load = inject(_reports_details_read, RuntimeError("reports unreadable"), skip=1, times=None)
    res = _act(action="remove_content", reason=None)
    assert load.hits == 2
    assert res.status_code == 200, res.text
    assert sorted(n["user_id"] for n in _notifications(db, "event_removed")) == sorted([MIA, ANA])


# ==== F-004: coded refusals when the target changes between the validation and the service ===========

def _promote(q):
    _profile_row(q.db, TOM)["role"] = "administrator"


def _suspend_elsewhere(q):
    _profile_row(q.db, TOM).update(suspended_at="2026-10-15T00:00:00+00:00", suspension_reason="by ADM2")


def _delete_profile(q):
    q.db.tables["profiles"] = [p for p in q.db.tables["profiles"] if p["id"] != TOM]


RACES = [
    ("warn", _promote, 400, "reported_user_is_administrator"),
    ("suspend", _promote, 400, "reported_user_is_administrator"),
    ("suspend", _suspend_elsewhere, 409, "already_suspended"),
    ("warn", _delete_profile, 404, "reported_user_not_found"),
    ("suspend", _delete_profile, 404, "reported_user_not_found"),
]


@pytest.mark.parametrize("kind", ["message", "event"])
@pytest.mark.parametrize("action,change,status,code", RACES,
                         ids=["warn_promoted", "suspend_promoted", "suspend_suspended", "warn_deleted",
                              "suspend_deleted"])
def test_a_change_between_validation_and_the_service_is_a_coded_refusal(db, inject, kind, action, change,
                                                                        status, code):
    _seed(db, kind)
    # the 1st profiles read is the validation; the 2nd is the service's own: change the target in between
    race = inject(_profiles_select, skip=1, times=1, effect=change)
    res = _act(action=action)
    assert race.hits == 1, "the target was never changed"
    assert res.status_code == status, res.text
    detail = res.json()["detail"]
    assert isinstance(detail, dict) and detail["code"] == code and detail["message"]
    _assert_reverted(db)
    assert _warnings(db) == [] and db.tables["notifications"] == []
    if action == "suspend" and change is not _delete_profile:
        reason = "by ADM2" if change is _suspend_elsewhere else None
        assert _profile_row(db, TOM)["suspension_reason"] == reason


def test_other_service_errors_pass_through_unchanged(db, inject):
    _seed(db, "message")
    boom = inject(_profiles_select, HTTPException(status_code=503, detail="profiles are down"), skip=1)
    res = _act(action="warn")
    assert boom.hits == 1
    assert res.status_code == 503 and res.json()["detail"] == "profiles are down"
    _assert_reverted(db)


# ==== F-005: the 422 for a bad reason points at body.reason ===========================================

def _reason_body(action, reason, missing):
    body = {"action": action}
    if not missing:
        body["reason"] = reason
    return body


@pytest.mark.parametrize("action", ["warn", "suspend"])
@pytest.mark.parametrize("reason,missing", [
    (None, True), (None, False), ("", False), ("   ", False), ("\n\t", False),
    ("x" * (WARNING_REASON_MAX_LENGTH + 1), False), (5, False), (["a"], False),
], ids=["missing", "null", "empty", "blank", "whitespace", "too_long", "number", "list"])
def test_a_bad_reason_is_422_located_at_body_reason(db, action, reason, missing):
    _seed(db, "message")
    res = client.post("/api/admin/reports/1/action", json=_reason_body(action, reason, missing))
    assert res.status_code == 422, res.text
    first = res.json()["detail"][0]
    assert list(first["loc"]) == ["body", "reason"], first
    _assert_open_unchanged(db)
    assert _warnings(db) == []


@pytest.mark.parametrize("reason,missing", [
    ("x" * (WARNING_REASON_MAX_LENGTH + 1), False), ("   ", False), ("", False), (None, False), (None, True),
], ids=["too_long", "blank", "empty", "null", "missing"])
def test_remove_content_ignores_any_reason(db, reason, missing):
    _seed(db, "event")
    res = client.post("/api/admin/reports/1/action", json=_reason_body("remove_content", reason, missing))
    assert res.status_code == 200, res.text
    assert res.json()["outcome"] == "content_removed"


@pytest.mark.parametrize("action", ["warn", "suspend"])
def test_the_reason_is_stripped_before_it_is_used(db, action):
    _seed(db, "user")
    assert _act(action=action, reason=f"   {REASON}\n").status_code == 200
    if action == "warn":
        assert _warnings(db)[0]["reason"] == REASON
    else:
        assert _profile_row(db, TOM)["suspension_reason"] == REASON


# ---- removal_incomplete: the removal stands, the owner was not warned, the admin must be told -------

def _undo_update(table):
    def when(q):
        return q.name == table and q.action == "update" and _payload(q).get("removed_at", "x") is None
    return when


@pytest.mark.parametrize("kind, table, row", [("event", "events", _event_row), ("message", "event_chats", _chat_row)])
def test_removal_incomplete_keeps_the_report_closed_audits_it_and_raises_the_error(db, inject, caplog, kind, table,
                                                                                    row):
    _seed(db, kind)
    warning = inject(_warnings_insert, RuntimeError("warnings are down"), times=None)
    undo = inject(_undo_update(table), RuntimeError("db down"))
    with caplog.at_level(logging.INFO):
        res = _act(action="remove_content", reason=None)
    assert warning.hits >= 1, "the warning insert was never reached"
    assert undo.hits == 1, "the undo failure was never injected"
    assert res.status_code == 500, res.text
    detail = res.json()["detail"]
    assert detail["code"] == "removal_incomplete" and "Tell a developer" in detail["message"]
    assert row(db)["removed_at"] is not None and row(db)["removed_by"] == ADM    # the removal stands
    report = _row(db)
    assert (report["status"], report["outcome"], report["closed_by"]) == ("action_taken", "content_removed", ADM)
    assert report["closed_at"] is not None
    logs = _report_logs(db)
    assert [l["action"] if "action" in l else l["type"] for l in logs] == ["report_action_taken"]
    assert "removal:incomplete" in logs[0]["values"]
    assert "outcome:content_removed" in logs[0]["values"] and "action:remove_content" in logs[0]["values"]
    assert logs[0]["entity_id"] == "1"
    assert _logged(caplog, logging.ERROR, "the action was done but the service raised afterwards")
    retry = _act(action="remove_content", reason=None)
    assert retry.status_code == 409 and _code(retry) == "report_closed"
    assert len(_report_logs(db)) == 1


@pytest.mark.parametrize("kind, row", [("event", _event_row), ("message", _chat_row)])
def test_removal_failed_with_a_successful_undo_still_reverts_the_report(db, inject, kind, row):
    _seed(db, kind)
    warning = inject(_warnings_insert, RuntimeError("warnings are down"), times=None)
    res = _act(action="remove_content", reason=None)
    assert warning.hits >= 1, "the warning insert was never reached"
    assert res.status_code == 500, res.text
    assert res.json()["detail"]["code"] == "removal_failed"
    assert row(db)["removed_at"] is None
    _assert_reverted(db)
