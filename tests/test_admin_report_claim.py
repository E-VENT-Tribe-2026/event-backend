"""Ticket #263 phase 1: concurrent report actions (the claim decides ONE winner).

Pinned design (see app/services/admin_report_action_service.py claim / revert):
  * claim() is ONE conditional update filtered on status = 'open' AND assigned_to = this admin. A non-empty
    result is the only direct win. After an empty result there is one re-read; the row is ours only when
    closed_by == this admin AND closed_at == this request's own claimed_at (an applied update with an empty
    PostgREST body). A loss is never a success. One retry with the same filters and claimed_at.
  * a loser answers, decided after the re-read: closed by anyone (also the same admin, other closed_at) ->
    409 report_closed; open, assigned to another admin -> 403 report_assigned_to_other; open, unassigned ->
    403 report_unassigned; open and assigned to this admin (retry failed too) -> 500 report_close_failed;
    gone -> 404. The action never runs for a loser and the loser changes nothing.
  * revert(..., claimed_at=...) reopens only the closure of THIS request (closed_at == claimed_at).
  * winner failure window: no effect -> reopened, a later request wins exactly once; unknown -> stays closed.

Interleavings are forced deterministically (no threads): a hook runs just before a request's claim update,
and may run a whole other request through the same TestClient.
"""
import inspect
import logging
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services import admin_report_action_service as svc
from tests import _fake_supabase
from tests.test_admin_reports_action_failures import (  # noqa: F401  (db and inject are fixtures)
    _payload, _reports_claim, _warnings_insert, _warnings_select, inject, server_errors,
)
from tests.test_admin_reports_actions import (  # noqa: F401
    ADM, ADM2, OLD_CLOSE, REASON, TOM, _act, _assert_open_unchanged, _assert_reverted, _code, _dismiss,
    _profile_row, _report_logs, _row, _seed, _snapshot, _warnings, client, db,
)

SECOND_REASON = "Second request, must never be used."


def _is_claim(q):
    return q.name == "reports" and q.action == "update" and _payload(q).get("status") in ("dismissed", "resolved")


@pytest.fixture
def claims(monkeypatch):
    """Script the claim updates (the updates of the reports table that close the report), in order.

    claims.steps[i] is a dict for the i-th claim update: before(query) runs first (it may run a whole other
    request), apply=False swallows the update (the row is not touched), empty=True answers an empty body
    (PostgREST RETURNING quirk) whether or not it applied, raises=exc raises exc instead of running the
    update (after `before`). Beyond the steps the update runs normally.
    claims.payloads records every claim payload, claims.calls their number. Claim updates issued from inside a
    `before` hook (the other request) are not scripted and not counted."""
    state = SimpleNamespace(steps=[], payloads=[], calls=0, depth=0)
    original = _fake_supabase.FakeQuery.execute

    def execute(self):
        if state.depth == 0 and _is_claim(self):
            index = state.calls
            state.calls += 1
            state.payloads.append(dict(_payload(self)))
            step = state.steps[index] if index < len(state.steps) else {}
            if step.get("before"):
                state.depth += 1
                try:
                    step["before"](self)
                finally:
                    state.depth -= 1
            if step.get("raises") is not None:
                raise step["raises"]
            result = original(self) if step.get("apply", True) else SimpleNamespace(data=[], count=None)
            if step.get("empty"):
                return SimpleNamespace(data=[], count=None)
            return result
        return original(self)

    monkeypatch.setattr(_fake_supabase.FakeQuery, "execute", execute)
    return state


# ---- request helpers ---------------------------------------------------------------------------------

DUPLICATES = [("event", "dismiss"), ("message", "warn"), ("user", "suspend"),
              ("event", "remove_content"), ("message", "remove_content")]
DUP_IDS = ["dismiss", "warn", "suspend", "remove_event", "remove_message"]


def _first(what):
    return _dismiss() if what == "dismiss" else _act(action=what, reason=None if what == "remove_content" else REASON)


def _second(what):
    return _dismiss() if what == "dismiss" else _act(
        action=what, reason=None if what == "remove_content" else SECOND_REASON)


def _assert_loser_changed_nothing(db, after_winner):
    assert _snapshot(db) == after_winner       # no warning, removal, suspension, audit entry or row change


# ==== (A) same-admin duplicate: both requests pass the early checks, request 1 claims and acts first =====

@pytest.mark.parametrize("kind,what", DUPLICATES, ids=DUP_IDS)
def test_same_admin_duplicate_request_loses_the_claim_with_409_and_does_nothing(db, claims, kind, what):
    _seed(db, kind)
    seen = {}

    def request_one(_q):
        res = _first(what)
        assert res.status_code == 200, res.text
        row = _row(db)
        seen["after"] = _snapshot(db)
        seen["closure"] = (row["status"], row["outcome"], row["closed_by"], row["closed_at"])

    claims.steps = [{"before": request_one}]
    res = _second(what)
    assert claims.calls >= 1 and "after" in seen, "request 1 never ran at the claim of request 2"
    assert res.status_code == 409, res.text
    assert _code(res) == "report_closed"
    _assert_loser_changed_nothing(db, seen["after"])
    row = _row(db)
    assert (row["status"], row["outcome"], row["closed_by"], row["closed_at"]) == seen["closure"]
    assert len(_report_logs(db)) == 1                                   # the winner's audit entry only
    if what == "warn":
        assert len(_warnings(db)) == 1 and _warnings(db)[0]["reason"] == REASON
    elif what == "suspend":
        assert _profile_row(db, TOM)["suspension_reason"] == REASON
    elif what == "remove_content":
        assert len(_warnings(db)) == 1                                  # the owner's removal warning, once
        assert [l["type"] for l in db.tables["logs"]].count("event_removed" if kind == "event"
                                                            else "message_removed") == 1
    else:
        assert _warnings(db) == []


# ==== (B) warn after a dismissal by the same admin ====================================================

def test_warn_paused_before_the_claim_loses_to_a_dismissal_of_the_same_admin(db, claims):
    _seed(db, "message")
    seen = {}

    def dismiss_meanwhile(_q):
        assert _dismiss().status_code == 200
        row = _row(db)
        seen["closure"] = (row["status"], row["outcome"], row["closed_by"], row["closed_at"])
        seen["after"] = _snapshot(db)

    claims.steps = [{"before": dismiss_meanwhile}]
    res = _act(action="warn")
    assert "after" in seen, "the dismissal never ran at the claim of the warn"
    assert res.status_code == 409, res.text
    assert _code(res) == "report_closed"
    assert _warnings(db) == []
    row = _row(db)
    assert (row["status"], row["outcome"], row["closed_by"], row["closed_at"]) == seen["closure"]
    assert row["status"] == "dismissed" and row["outcome"] == "dismissed" and row["closed_by"] == ADM
    _assert_loser_changed_nothing(db, seen["after"])
    assert [l["type"] for l in _report_logs(db)] == ["report_dismissed"]


# ==== (C) reassignment between the assignment check and the claim =====================================

def _reassign_to_other(_q):
    assert client.post("/api/admin/reports/1/unassign").status_code == 200
    assert client.post("/api/admin/reports/1/assign", json={"admin_id": ADM2}).status_code == 200


def _unassign_only(_q):
    assert client.post("/api/admin/reports/1/unassign").status_code == 200


def _no_action_audit(db):
    types = [l["type"] for l in _report_logs(db)]
    assert "report_dismissed" not in types and "report_action_taken" not in types, types


@pytest.mark.parametrize("what", ["dismiss", "warn", "suspend", "remove_content"])
def test_request_paused_after_the_assignment_check_loses_when_the_report_goes_to_another_admin(db, claims, what):
    _seed(db, "message")
    claims.steps = [{"before": _reassign_to_other}]
    res = _first(what)
    assert claims.calls >= 1
    assert res.status_code == 403, res.text
    assert _code(res) == "report_assigned_to_other"
    row = _row(db)
    assert row["assigned_to"] == ADM2
    assert row["status"] == "open" and row["outcome"] is None and row["closed_by"] is None \
        and row["closed_at"] is None, row
    assert _warnings(db) == [] and _profile_row(db, TOM)["suspended_at"] is None
    assert _snapshot(db)["event_chats"][0]["removed_at"] is None
    _no_action_audit(db)


@pytest.mark.parametrize("what", ["dismiss", "warn", "suspend", "remove_content"])
def test_request_paused_after_the_assignment_check_loses_when_the_report_is_unassigned(db, claims, what):
    _seed(db, "message")
    claims.steps = [{"before": _unassign_only}]
    res = _first(what)
    assert claims.calls >= 1
    assert res.status_code == 403, res.text
    assert _code(res) == "report_unassigned"
    row = _row(db)
    assert row["assigned_to"] is None
    assert row["status"] == "open" and row["outcome"] is None and row["closed_by"] is None \
        and row["closed_at"] is None, row
    assert _warnings(db) == [] and _profile_row(db, TOM)["suspended_at"] is None
    assert _snapshot(db)["event_chats"][0]["removed_at"] is None
    _no_action_audit(db)


# ==== (D) claim details ================================================================================

@pytest.mark.parametrize("what", ["dismiss", "warn"])
def test_d1_an_update_that_applied_with_an_empty_body_counts_as_a_win(db, claims, what):
    _seed(db, "message")
    claims.steps = [{"empty": True}]
    res = _first(what)
    assert res.status_code == 200, res.text
    assert claims.calls == 1, "an applied update must not be retried"
    row = _row(db)
    assert row["closed_by"] == ADM
    assert row["closed_at"] == claims.payloads[0]["closed_at"]          # closed by THIS request's claim
    assert res.json()["closed_at"] == row["closed_at"]
    if what == "warn":
        assert len(_warnings(db)) == 1
    assert len(_report_logs(db)) == 1


@pytest.mark.parametrize("what", ["dismiss", "warn"])
def test_d2_a_first_attempt_that_did_not_apply_is_retried_with_the_same_claimed_at(db, claims, what):
    _seed(db, "message")
    claims.steps = [{"apply": False}]                                    # row stays open and assigned to ADM
    res = _first(what)
    assert res.status_code == 200, res.text
    assert claims.calls == 2
    assert claims.payloads[0] == claims.payloads[1]                      # same patch, same claimed_at
    row = _row(db)
    assert (row["closed_by"], row["closed_at"]) == (ADM, claims.payloads[0]["closed_at"])
    if what == "warn":
        assert len(_warnings(db)) == 1
    assert len(_report_logs(db)) == 1


@pytest.mark.parametrize("what", ["dismiss", "warn"])
def test_d3_a_closure_by_the_same_admin_with_another_closed_at_is_a_loss(db, claims, what):
    _seed(db, "message")

    def same_admin_closed_it(_q):
        _row(db).update(status="dismissed", outcome="dismissed", closed_by=ADM, closed_at=OLD_CLOSE)

    claims.steps = [{"before": same_admin_closed_it}]
    before_logs = list(db.tables["logs"])
    res = _first(what)
    assert res.status_code == 409, res.text
    assert _code(res) == "report_closed"
    row = _row(db)
    assert (row["status"], row["outcome"], row["closed_by"], row["closed_at"]) == \
           ("dismissed", "dismissed", ADM, OLD_CLOSE)
    assert _warnings(db) == [] and db.tables["logs"] == before_logs


@pytest.mark.parametrize("what", ["dismiss", "warn"])
def test_d4_another_admins_closure_met_on_the_retry_is_a_loss(db, claims, what):
    _seed(db, "message")

    def other_admin_closed_it(_q):
        _row(db).update(status="dismissed", outcome="dismissed", closed_by=ADM2, closed_at=OLD_CLOSE)

    claims.steps = [{"apply": False}, {"before": other_admin_closed_it}]
    res = _first(what)
    assert claims.calls == 2
    assert res.status_code == 409, res.text
    assert _code(res) == "report_closed"
    row = _row(db)
    assert (row["status"], row["outcome"], row["closed_by"], row["closed_at"]) == \
           ("dismissed", "dismissed", ADM2, OLD_CLOSE)
    assert _warnings(db) == [] and _report_logs(db) == []


@pytest.mark.parametrize("what", ["dismiss", "warn"])
def test_d5_both_attempts_failing_with_the_row_open_and_mine_is_500_report_close_failed(db, claims, what):
    _seed(db, "message")
    claims.steps = [{"apply": False}, {"apply": False}]
    res = _first(what)
    assert claims.calls == 2
    assert res.status_code == 500, res.text
    assert _code(res) == "report_close_failed"
    _assert_open_unchanged(db)
    assert _row(db)["assigned_to"] == ADM
    assert _warnings(db) == [] and _report_logs(db) == []


# ==== revert: only the closure this request made ========================================================

def _closed_by_adm(db):
    _seed(db, "message", status="resolved", outcome="warned", closed_by=ADM, closed_at=OLD_CLOSE)


def test_r1_revert_with_a_different_claimed_at_leaves_the_closure_alone(db):
    _closed_by_adm(db)
    svc.revert(1, "resolved", ADM, "warned", "warn", claimed_at="2026-10-10T00:00:00+00:00")
    row = _row(db)
    assert (row["status"], row["outcome"], row["closed_by"], row["closed_at"]) == \
           ("resolved", "warned", ADM, OLD_CLOSE)
    assert _report_logs(db) == []                                        # not flagged as an unreverted closure


def test_r2_revert_with_the_matching_claimed_at_reopens(db):
    _closed_by_adm(db)
    assert svc.revert(1, "resolved", ADM, "warned", "warn", claimed_at=OLD_CLOSE) is True
    _assert_open_unchanged(db)


def test_a_failed_action_does_not_reopen_a_closure_of_the_same_admin_made_by_another_request(db, inject):
    """The warn fails and, meanwhile, ANOTHER request of the same admin closed the report (other closed_at)."""
    _seed(db, "message")

    def same_admin_other_request_closes(_q):
        _row(db).update(closed_by=ADM, closed_at=OLD_CLOSE)     # same status and outcome, other closed_at

    service = inject(_warnings_insert, HTTPException(status_code=503, detail="warnings are down"),
                     effect=same_admin_other_request_closes)
    res = _act(action="warn")
    assert service.hits == 1
    assert res.status_code == 503, res.text
    row = _row(db)
    assert (row["status"], row["outcome"], row["closed_by"], row["closed_at"]) == \
           ("resolved", "warned", ADM, OLD_CLOSE)


@pytest.mark.parametrize("what", ["dismiss", "warn"])
def test_every_caller_passes_its_claimed_at_to_revert(db, inject, monkeypatch, what):
    _seed(db, "message")
    seen = []
    original = svc.revert

    def spy(*args, **kwargs):
        seen.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(svc, "revert", spy)
    payloads = []
    inject(_reports_claim, RuntimeError("response lost"), after=True,    # applied, then the response is lost
           effect=lambda q: payloads.append(dict(_payload(q))))
    if what == "dismiss":
        res = server_errors.post("/api/admin/reports/1/dismiss")
    else:
        res = server_errors.post("/api/admin/reports/1/action", json={"action": "warn", "reason": REASON})
    assert res.status_code == 500, res.text
    assert len(seen) == 1, seen
    args, kwargs = seen[0]
    passed = inspect.signature(original).bind(*args, **kwargs).arguments.get("claimed_at")
    claim_payload = next(p for p in payloads if p.get("status") in ("dismissed", "resolved"))
    assert passed == claim_payload["closed_at"]
    _assert_reverted(db)


# ==== winner failure window ==============================================================================

def test_w1_a_winner_whose_action_failed_without_effect_reopens_and_a_later_request_wins_once(db, inject):
    _seed(db, "message")
    service = inject(_warnings_insert, HTTPException(status_code=503, detail="warnings are down"))
    res = _act(action="warn")
    assert service.hits == 1
    assert res.status_code == 503, res.text
    _assert_reverted(db)
    assert _row(db)["assigned_to"] == ADM                                # still assigned: the retry may claim
    again = _act(action="warn")
    assert again.status_code == 200, again.text
    assert len(_warnings(db)) == 1
    row = _row(db)
    assert (row["status"], row["outcome"], row["closed_by"]) == ("resolved", "warned", ADM)
    third = _act(action="warn")
    assert third.status_code == 409 and _code(third) == "report_closed"
    assert len(_warnings(db)) == 1


def test_w2_a_winner_with_an_unknown_action_result_stays_closed_and_a_loser_gets_409(db, inject):
    _seed(db, "message")
    service = inject(_warnings_insert, HTTPException(status_code=503, detail="warnings are down"))
    check = inject(_warnings_select, RuntimeError("cannot look"), times=None)
    res = _act(action="warn")
    assert service.hits == 1 and check.hits >= 1
    assert res.status_code == 503, res.text
    after_winner = _snapshot(db)
    row = _row(db)
    assert (row["status"], row["outcome"], row["closed_by"]) == ("resolved", "warned", ADM)
    assert [l["type"] for l in _report_logs(db)] == ["report_close_unreverted"]
    loser = _act(action="warn", reason=SECOND_REASON)
    assert loser.status_code == 409, loser.text
    assert _code(loser) == "report_closed"
    assert _snapshot(db) == after_winner


# ==== F-001: the claim stamp is strictly increasing ======================================================

def _fixed_clock(monkeypatch, quantum_us=None):
    """Make svc.datetime.now() coarse: a constant instant (quantum_us None) or the real time floored to
    quantum_us microseconds (15.6 ms is the Windows tick). Resets the per-process last stamp."""
    frozen = datetime(2026, 11, 1, 12, 0, 0, 123000, tzinfo=timezone.utc)

    class CoarseDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if quantum_us is None:
                return frozen
            real = datetime.now(timezone.utc)
            return real.replace(microsecond=real.microsecond // quantum_us * quantum_us)

    monkeypatch.setattr(svc, "datetime", CoarseDatetime)
    monkeypatch.setattr(svc, "_last_stamp", None)


@pytest.mark.parametrize("quantum_us", [None, 15600], ids=["constant", "15.6ms"])
def test_claim_stamp_is_strictly_increasing_under_a_coarse_clock(monkeypatch, quantum_us):
    _fixed_clock(monkeypatch, quantum_us)
    stamps = [svc._claim_stamp() for _ in range(2000)]
    parsed = [datetime.fromisoformat(x) for x in stamps]
    assert all(a < b for a, b in zip(parsed, parsed[1:]))
    assert len(set(stamps)) == len(stamps)


@pytest.mark.parametrize("quantum_us", [None, 15600], ids=["constant", "15.6ms"])
def test_same_admin_duplicate_warn_is_a_409_under_a_coarse_clock(db, claims, monkeypatch, quantum_us):
    _fixed_clock(monkeypatch, quantum_us)
    _seed(db, "message")
    seen = {}

    def request_one(_q):
        res = _first("warn")
        assert res.status_code == 200, res.text
        seen["after"] = _snapshot(db)

    claims.steps = [{"before": request_one}]
    res = _second("warn")
    assert "after" in seen
    assert res.status_code == 409, res.text
    assert _code(res) == "report_closed"
    assert len(_warnings(db)) == 1 and _warnings(db)[0]["reason"] == REASON
    _assert_loser_changed_nothing(db, seen["after"])
    assert len(_report_logs(db)) == 1


# ==== F-005 additions ====================================================================================

def test_claim_404_when_the_row_disappears_between_the_early_load_and_the_claim(db, claims):
    _seed(db, "message")
    seen = {}

    def row_vanishes(_q):
        db.tables["reports"].remove(_row(db))
        seen["after"] = _snapshot(db)

    claims.steps = [{"before": row_vanishes}]
    res = _act(action="warn")
    assert "after" in seen
    assert res.status_code == 404, res.text
    assert _code(res) == "report_not_found"
    assert claims.calls == 1
    _assert_loser_changed_nothing(db, seen["after"])


@pytest.mark.parametrize("closed_at", [OLD_CLOSE, "2026-10-10T00:00:00+00:00", None])
def test_revert_without_claimed_at_reopens_a_closure_of_the_same_admin_whatever_its_closed_at(db, closed_at):
    _seed(db, "message", status="resolved", outcome="warned", closed_by=ADM, closed_at=closed_at)
    assert svc.revert(1, "resolved", ADM, "warned", "warn", claimed_at=None) is True
    _assert_open_unchanged(db)


def _post(what):
    if what == "dismiss":
        return server_errors.post("/api/admin/reports/1/dismiss")
    return server_errors.post("/api/admin/reports/1/action", json={"action": "warn", "reason": REASON})


@pytest.mark.parametrize("failure", ["update_raises", "reread_raises"])
@pytest.mark.parametrize("what", ["dismiss", "warn"])
def test_a_non_http_error_in_the_claim_propagates_and_reverts_with_this_requests_claimed_at(
        db, claims, monkeypatch, what, failure):
    _seed(db, "message")
    calls = []
    original = svc.revert

    def spy(*args, **kwargs):
        calls.append(inspect.signature(original).bind(*args, **kwargs).arguments)
        return original(*args, **kwargs)

    def reread_fails(_report_id):
        raise RuntimeError("re-read failed")

    monkeypatch.setattr(svc, "revert", spy)
    if failure == "update_raises":
        claims.steps = [{"raises": RuntimeError("database is down")}]
    else:
        claims.steps = [{"apply": False}]
        monkeypatch.setattr(svc, "_row_of", reread_fails)
    res = _post(what)
    assert res.status_code == 500, res.text
    assert claims.calls == 1
    assert len(calls) == 1, calls
    assert calls[0].get("claimed_at") == claims.payloads[0]["closed_at"]
    _assert_reverted(db)
    assert _warnings(db) == []


@pytest.mark.parametrize("what", ["dismiss", "warn"])
def test_d6_an_empty_body_on_the_second_attempt_counts_as_a_win(db, claims, what):
    _seed(db, "message")
    claims.steps = [{"apply": False}, {"empty": True}]                   # attempt 2 applies, answers nothing
    res = _first(what)
    assert res.status_code == 200, res.text
    assert claims.calls == 2
    assert claims.payloads[0] == claims.payloads[1]
    row = _row(db)
    assert (row["closed_by"], row["closed_at"]) == (ADM, claims.payloads[0]["closed_at"])
    if what == "warn":
        assert len(_warnings(db)) == 1
    assert len(_report_logs(db)) == 1


@pytest.mark.parametrize("what", ["dismiss", "warn"])
@pytest.mark.parametrize("scenario,status,code", [
    ("reassigned", 403, "report_assigned_to_other"),
    ("unassigned", 403, "report_unassigned"),
    ("closed_by_same_admin", 409, "report_closed"),
])
def test_d7_after_an_unapplied_first_attempt_the_reread_decides_the_loss(db, claims, what, scenario, status, code):
    _seed(db, "message")

    def closed_by_same_admin(_q):
        _row(db).update(status="dismissed", outcome="dismissed", closed_by=ADM, closed_at=OLD_CLOSE)

    hook = {"reassigned": _reassign_to_other, "unassigned": _unassign_only,
            "closed_by_same_admin": closed_by_same_admin}[scenario]
    claims.steps = [{"apply": False}, {"before": hook}]
    res = _first(what)
    assert claims.calls == 2
    assert res.status_code == status, res.text
    assert _code(res) == code
    assert _warnings(db) == []
    _no_action_audit(db)
    assert _row(db)["status"] == ("dismissed" if scenario == "closed_by_same_admin" else "open")
    if scenario == "closed_by_same_admin":
        row = _row(db)
        assert (row["status"], row["closed_by"], row["closed_at"]) == ("dismissed", ADM, OLD_CLOSE)


@pytest.mark.parametrize("a,b", [
    ("2026-01-01T00:00:00.12345+00:00", "2026-01-01T00:00:00.123450+00:00"),
    ("2026-01-01T00:00:00.1+00:00", "2026-01-01T00:00:00.100000+00:00"),
    ("2026-01-01T00:00:00Z", "2026-01-01T00:00:00+00:00"),
    ("2026-01-01T01:00:00+01:00", "2026-01-01T00:00:00+00:00"),
    ("2026-01-01T00:00:00", "2026-01-01T00:00:00+00:00"),
    ("2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00"),
], ids=["5-vs-6-digits", "1-vs-6-digits", "Z", "offset", "naive-a", "naive-b"])
def test_same_moment_accepts_other_textual_forms_of_one_instant(a, b):
    assert svc._same_moment(a, b) is True
    assert svc._same_moment(b, a) is True


@pytest.mark.parametrize("a,b", [
    ("2026-01-01T00:00:00.000001+00:00", "2026-01-01T00:00:00.000002+00:00"),
    ("", "2026-01-01T00:00:00+00:00"),
    ("2026-01-01T00:00:00+00:00", ""),
    (None, "2026-01-01T00:00:00+00:00"),
    ("2026-01-01T00:00:00+00:00", None),
], ids=["1us-apart", "empty-a", "empty-b", "none-a", "none-b"])
def test_same_moment_rejects_different_or_missing_moments(a, b):
    assert svc._same_moment(a, b) is False


def test_same_moment_garbage_is_false_and_logs_a_warning(caplog):
    with caplog.at_level(logging.WARNING, logger=svc.logger.name):
        assert svc._same_moment("not a timestamp", "2026-01-01T00:00:00+00:00") is False
    assert any("Could not compare timestamps" in r.getMessage() for r in caplog.records)
