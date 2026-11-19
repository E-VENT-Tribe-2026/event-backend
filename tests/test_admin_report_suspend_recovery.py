"""Ticket #264: finishing a partly applied suspension through a report.

suspend_user marks the profile first and then cancels the upcoming events; when that fails the answer is
503 suspension_effects_incomplete and the report is reopened. Retrying Suspend through a report must then
finish the leftover effects instead of being rejected with 409 already_suspended, while a genuine
duplicate (suspended, nothing pending) is still refused.

Same world, helpers and fake database as tests/test_admin_reports_actions.py and
tests/test_admin_reports_action_failures.py (real services, in-memory Supabase fake, no network).
TOM is the reported user; he organizes EV1 and EV3 (both upcoming) and takes part in both.
Every injected failure asserts that it was really hit.
"""
import copy
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.core.dependencies import require_admin
from app.services import admin_service, suspension_service
from tests.test_admin_reports_action_failures import (  # noqa: F401  (db, client and inject are fixtures)
    _notifications, _profiles_select, inject,
)
from tests.test_admin_reports_actions import (  # noqa: F401
    ADM2, ANA, EV1, EV2, MIA, REASON, TOM,
    _act, _assert_closed_response, _assert_open_unchanged, _assert_reverted, _code, _event, _event_row,
    _profile_row, _row, _seed, client, db,
)

EV3 = "7c1d2e3f-4a5b-4c6d-8e7f-1a2b3c4d5e6f"     # second upcoming event organized by TOM
RETRY_REASON = "Second attempt: the first one died halfway."


# ---- world and helpers ----------------------------------------------------------------------------

@pytest.fixture
def two_events(db):
    """TOM organizes EV1 and EV3; he and MIA joined EV3 (EV1: TOM, MIA, ANA already)."""
    db.tables["events"].append(_event(EV3, "Picnic", TOM))
    db.tables["event_participants"] += [{"id": 10, "event_id": EV3, "user_id": TOM, "status": "going"},
                                        {"id": 11, "event_id": EV3, "user_id": MIA, "status": "going"}]
    return db


def _as_admin(uid):
    from app.main import app
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id=uid)


def _cancel_update(q):
    return (q.name == "events" and q.action == "update"
            and (q.payload or {}).get("status") == "cancelled")


def _first_attempt(db, inject, skip=0, rid=1):
    """Suspend through report `rid`, failing in the skip+1-th event cancellation: 503, report reopened."""
    rule = inject(_cancel_update, RuntimeError("events went away"), skip=skip)
    res = _act(rid, action="suspend", reason=REASON)
    assert rule.hits == 1, "the failure was never injected"
    assert res.status_code == 503, res.text
    assert _code(res) == "suspension_effects_incomplete"
    _assert_open_unchanged(db, rid)
    assert _profile_row(db, TOM)["suspended_at"] is not None
    return res


def _cancel_notes(db, event_id):
    return sorted(n["user_id"] for n in _notifications(db, "event_cancelled") if n["event_id"] == event_id)


def _suspension_audit(db):
    return [l for l in db.tables["logs"] if l["type"] == "account_suspended"]


def _finish_elsewhere(q):
    """Another administrator completes the recovery: every event of TOM cancelled, his joins removed."""
    for ev in q.db.tables["events"]:
        if ev.get("created_by") == TOM:
            ev["status"] = "cancelled"
    q.db.tables["event_participants"] = [p for p in q.db.tables["event_participants"] if p["user_id"] != TOM]


def _audit_values(entry):
    """The audit `values` tokens ("key:value") as an exact {key: value} dict (no substring matching)."""
    return dict(token.split(":", 1) for token in entry["values"])


def _events_select(q):
    return q.name == "events" and q.action == "select"


def _recovery_records(caplog):
    return [r for r in caplog.records
            if r.name == "app.services.suspension_service" and r.levelno == logging.INFO]


def _fully_suspended(db):
    """A completed suspension: nothing left to do."""
    _profile_row(db, TOM).update(suspended_at="2026-10-15T00:00:00+00:00", suspension_reason="done earlier")
    _finish_elsewhere(SimpleNamespace(db=db))


# ==== 1. the ticket scenario ==========================================================================

def test_retry_through_a_second_report_finishes_the_suspension(db, two_events, inject):
    """503 on the first report, then another administrator's Suspend on a second report succeeds."""
    _seed(db, "user", 1)
    _seed(db, "user", 2, assigned_to=ADM2)
    _first_attempt(db, inject)
    before = dict(_profile_row(db, TOM))

    _as_admin(ADM2)
    res = _act(2, action="suspend", reason=RETRY_REASON)
    assert res.status_code == 200, res.text
    _assert_closed_response(db, res, 2, "resolved", "suspended", admin=ADM2)
    tom = _profile_row(db, TOM)
    assert tom["suspended_at"] == before["suspended_at"]
    assert tom["suspension_reason"] == before["suspension_reason"] == REASON
    assert all(_event_row(db, e)["status"] == "cancelled" for e in (EV1, EV3))
    assert not any(p["user_id"] == TOM for p in db.tables["event_participants"])
    _assert_open_unchanged(db, 1)                      # the first report was only reopened, never closed


def test_retry_through_the_same_report_finishes_the_suspension(db, two_events, inject):
    """The same report, reopened by the failure, can simply be actioned again."""
    _seed(db, "user")
    _first_attempt(db, inject)
    reason = _profile_row(db, TOM)["suspension_reason"]
    res = _act(action="suspend", reason=RETRY_REASON)
    assert res.status_code == 200, res.text
    _assert_closed_response(db, res, 1, "resolved", "suspended")
    assert _profile_row(db, TOM)["suspension_reason"] == reason


# ==== 2. no duplicated side effects ===================================================================

def test_recovery_notifies_once_per_event_and_writes_one_audit_entry(db, two_events, inject, caplog):
    """EV1 was cancelled by the first attempt, EV3 failed: the retry must only do EV3."""
    _seed(db, "user")
    _first_attempt(db, inject, skip=1)
    assert _event_row(db, EV1)["status"] == "cancelled" and _event_row(db, EV3)["status"] == "active"
    assert _cancel_notes(db, EV1) == sorted([MIA, ANA])
    assert _suspension_audit(db) == []                 # the failed attempt wrote no audit entry

    _row(db)["assigned_to"] = ADM2                     # handed over to the recovering administrator
    _as_admin(ADM2)
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="app.services.suspension_service"):
        res = _act(action="suspend", reason=RETRY_REASON)
    assert res.status_code == 200, res.text
    records = _recovery_records(caplog)
    assert len(records) == 1, [r.getMessage() for r in records]
    message = records[0].getMessage()
    assert TOM in message and "1 events cancelled" in message and "2 participations removed" in message
    assert RETRY_REASON not in message and REASON not in message
    assert _cancel_notes(db, EV1) == sorted([MIA, ANA])    # not told a second time
    assert _cancel_notes(db, EV3) == [MIA]
    audit = _suspension_audit(db)
    assert len(audit) == 1, audit
    entry = audit[0]
    assert entry["created_by_id"] == ADM2 and entry["entity_id"] == TOM
    assert _audit_values(entry) == {
        "reason": RETRY_REASON,
        "cancelled_events_count": "1",                # only EV3, done by the retry
        "joined_events_removed_count": "2",           # TOM left EV1 and EV3 on the retry
        "retried": "True",
    }


# ==== 3. a genuine duplicate is still refused =========================================================

def test_a_fully_suspended_account_with_nothing_pending_is_still_refused(db, two_events):
    _seed(db, "user")
    _fully_suspended(db)
    before = copy.deepcopy(db.tables)
    res = _act(action="suspend", reason=RETRY_REASON)
    assert res.status_code == 409, res.text
    assert _code(res) == "already_suspended"
    assert db.tables == before                         # report still open and unclaimed, no audit, no notes
    assert db.tables["notifications"] == [] and db.tables["logs"] == []
    _assert_open_unchanged(db)


# ==== 4. a second failure halfway =====================================================================

def test_a_second_failure_halfway_reopens_again_and_a_third_attempt_completes(db, two_events, inject):
    _seed(db, "user")
    _first_attempt(db, inject, skip=0)                 # nothing cancelled yet
    assert _cancel_notes(db, EV1) == [] and _cancel_notes(db, EV3) == []

    again = inject(_cancel_update, RuntimeError("events went away again"), skip=1)    # EV1 ok, EV3 fails
    res = _act(action="suspend", reason=RETRY_REASON)
    assert again.hits == 1, "the second failure was never injected"
    assert res.status_code == 503, res.text
    assert _code(res) == "suspension_effects_incomplete"
    _assert_reverted(db)
    assert _event_row(db, EV1)["status"] == "cancelled" and _event_row(db, EV3)["status"] == "active"
    assert _suspension_audit(db) == []

    res = _act(action="suspend", reason=RETRY_REASON)
    assert res.status_code == 200, res.text
    _assert_closed_response(db, res, 1, "resolved", "suspended")
    assert _cancel_notes(db, EV1) == sorted([MIA, ANA])
    assert _cancel_notes(db, EV3) == [MIA]
    assert len(_suspension_audit(db)) == 1


# ==== 5. another administrator finishes between the pre-check and the service ==========================

def test_recovery_finished_elsewhere_after_the_precheck_is_refused_and_reopens_the_report(db, two_events, inject):
    _seed(db, "user")
    _first_attempt(db, inject)
    # the 1st profiles read of the retry is the validation, the 2nd is the service's own
    race = inject(_profiles_select, skip=1, times=1, effect=_finish_elsewhere)
    res = _act(action="suspend", reason=RETRY_REASON)
    assert race.hits == 1, "the recovery was never finished in between (the pre-check refused first)"
    assert res.status_code == 409, res.text
    assert _code(res) == "already_suspended"
    _assert_reverted(db)
    assert _suspension_audit(db) == []


# ==== 6. two reports about the same user ==============================================================

def test_the_second_report_about_a_recovered_user_is_refused_before_any_claim_and_stays_open(db, two_events, inject):
    _seed(db, "user", 1)
    _seed(db, "user", 2)
    _first_attempt(db, inject, rid=1)
    assert _act(1, action="suspend", reason=RETRY_REASON).status_code == 200
    res = _act(2, action="suspend", reason=RETRY_REASON)
    assert res.status_code == 409, res.text
    assert _code(res) == "already_suspended"
    _assert_open_unchanged(db, 2)
    assert _row(db, 1)["outcome"] == "suspended"
    assert len(_suspension_audit(db)) == 1


# ==== 7. the report flow answers like the standalone endpoint =========================================

def test_the_report_503_body_equals_the_standalone_endpoint_503_body(db, two_events, inject):
    _seed(db, "user")
    via_report = _first_attempt(db, inject).json()["detail"]
    again = inject(_cancel_update, RuntimeError("events went away"), skip=0)
    standalone = client.post(f"/api/admin/users/{TOM}/suspend", json={"reason": RETRY_REASON})
    assert again.hits == 1, "the standalone failure was never injected"
    assert standalone.status_code == 503, standalone.text
    detail = standalone.json()["detail"]
    assert via_report == detail
    assert detail["code"] == "suspension_effects_incomplete" and detail["user_id"] == TOM
    assert detail["suspended_since"] == _profile_row(db, TOM)["suspended_at"]


# ==== 9. what the helper-based pre-check does when its read fails (F-001) ============================

def _suspended_with_pending(db):
    _profile_row(db, TOM).update(suspended_at="2026-10-15T00:00:00+00:00", suspension_reason="first try")


def test_a_failing_precheck_read_counts_as_pending_and_the_service_answers_the_coded_503(db, two_events, inject, caplog):
    """Suspended, events pending. The pre-check's events read fails and so does the service's own (times=2):
    the request is not a bare 500 but the coded 503, the report is reopened, suspended_at is unchanged."""
    _seed(db, "user")
    _suspended_with_pending(db)
    before = _profile_row(db, TOM)["suspended_at"]
    rule = inject(_events_select, RuntimeError("events unreadable"), times=2)
    with caplog.at_level(logging.WARNING, logger="app.services.admin_report_action_service"):
        res = _act(action="suspend", reason=RETRY_REASON)
    assert rule.hits == 2, "the pre-check and the service read were not both hit"
    assert res.status_code == 503, res.text
    assert _code(res) == "suspension_effects_incomplete"
    _assert_open_unchanged(db)
    assert _profile_row(db, TOM)["suspended_at"] == before
    assert _suspension_audit(db) == []
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING
                and r.name == "app.services.admin_report_action_service"]
    assert len(warnings) == 1 and "RuntimeError" in warnings[0] and TOM not in warnings[0]


def test_a_precheck_read_failing_once_lets_the_retry_complete(db, two_events, inject):
    """Only the pre-check read fails (times=1): it counts as pending, the service's own reads succeed,
    so the recovery legitimately completes with 200."""
    _seed(db, "user")
    _suspended_with_pending(db)
    before = _profile_row(db, TOM)["suspended_at"]
    rule = inject(_events_select, RuntimeError("blip"), times=1)
    res = _act(action="suspend", reason=RETRY_REASON)
    assert rule.hits == 1, "the pre-check failure was never injected"
    assert res.status_code == 200, res.text
    _assert_closed_response(db, res, 1, "resolved", "suspended")
    assert _profile_row(db, TOM)["suspended_at"] == before
    assert all(_event_row(db, e)["status"] == "cancelled" for e in (EV1, EV3))


# ==== 10. a retry that only has participations left (F-003) ===========================================

def test_a_failed_participation_delete_is_finished_by_the_retry_without_renotifying(db, two_events, inject):
    _seed(db, "user")
    rule = inject(lambda q: q.name == "event_participants" and q.action == "delete",
                  RuntimeError("participants went away"))
    res = _act(action="suspend", reason=REASON)
    assert rule.hits == 1, "the failure was never injected"
    assert res.status_code == 503, res.text
    assert _code(res) == "suspension_effects_incomplete"
    _assert_open_unchanged(db)
    assert all(_event_row(db, e)["status"] == "cancelled" for e in (EV1, EV3))   # cancelled before the delete
    notes = {e: _cancel_notes(db, e) for e in (EV1, EV3)}
    assert any(p["user_id"] == TOM for p in db.tables["event_participants"])

    res = _act(action="suspend", reason=RETRY_REASON)
    assert res.status_code == 200, res.text
    _assert_closed_response(db, res, 1, "resolved", "suspended")
    assert {e: _cancel_notes(db, e) for e in (EV1, EV3)} == notes      # no new event_cancelled notifications
    (entry,) = _suspension_audit(db)
    values = _audit_values(entry)
    assert values["cancelled_events_count"] == "0"
    assert int(values["joined_events_removed_count"]) > 0
    assert values["retried"] == "True"


# ==== 11. the recovery log line (F-004) ===============================================================

def test_no_recovery_log_line_on_a_first_suspend(db, two_events, caplog):
    _seed(db, "user")
    with caplog.at_level(logging.INFO, logger="app.services.suspension_service"):
        res = _act(action="suspend", reason=REASON)
    assert res.status_code == 200, res.text
    assert _recovery_records(caplog) == []


def test_no_recovery_log_line_on_a_rejected_duplicate(db, two_events, caplog):
    _seed(db, "user")
    _fully_suspended(db)
    with caplog.at_level(logging.INFO, logger="app.services.suspension_service"):
        res = _act(action="suspend", reason=RETRY_REASON)
    assert res.status_code == 409, res.text
    assert _recovery_records(caplog) == []


# ==== 12. two administrators recovering at once (F-002) ===============================================

def test_an_event_cancelled_by_another_admin_in_between_is_not_notified_or_counted_twice(db, two_events, inject, frozen_now):
    """EV1 is cancelled elsewhere between the selection and the cancel update: this call skips it."""
    def cancel_ev1_elsewhere(q):
        _event_row(db, EV1)["status"] = "cancelled"

    race = inject(_cancel_update, skip=0, times=1, effect=cancel_ev1_elsewhere)
    cancelled, removed = admin_service.end_upcoming_activity(TOM, "reason", "Event '{title}' cancelled")
    assert race.hits == 1, "the other administrator never got in between"
    assert cancelled == 1, "only EV3 was cancelled by this call"
    assert _cancel_notes(db, EV1) == []
    assert _cancel_notes(db, EV3) == [MIA]
    assert _event_row(db, EV3)["status"] == "cancelled"
    assert removed == 2


# ==== 8. helper parity with end_upcoming_activity =====================================================

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)
FUTURE_ISO = "2031-01-01T00:00:00+00:00"
PAST_ISO = "2029-01-01T00:00:00+00:00"


class _Frozen(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz is None else NOW.astimezone(tz)


@pytest.fixture
def frozen_now():
    """The selection compares start_datetime >= now: pin 'now' wherever the selection may live."""
    patches = [patch.object(m, "datetime", _Frozen) for m in (admin_service, suspension_service)
               if hasattr(m, "datetime")]
    for p in patches:
        p.start()
    yield NOW
    for p in patches:
        p.stop()


STATES = {                                   # state -> (start_datetime, status, removed_at)
    "upcoming": (FUTURE_ISO, "active", None),
    "past": (PAST_ISO, "active", None),
    "cancelled": (FUTURE_ISO, "cancelled", None),
    "removed": (FUTURE_ISO, "active", "2029-12-01T00:00:00+00:00"),
    "starting_now": (NOW.isoformat(), "active", None),
    "unparsable": ("not-a-date", "active", None),
    "naive_future": ("2031-01-01T00:00:00", "active", None),    # no offset: read as UTC
    "naive_past": ("2029-01-01T00:00:00", "active", None),
    "null_start": (None, "active", None),                       # no start: never "upcoming"
}
# A null `status` is not modelled by the fake (its neq would not match NULL like SQL does), so it is not a case.
# what end_upcoming_activity does today: organized events need upcoming + not cancelled + not removed,
# joined ones only need to be upcoming (the participation is dropped even from a cancelled/removed event)
EXPECTED = {
    "organized": {"upcoming": True, "past": False, "cancelled": False, "removed": False,
                  "starting_now": True, "unparsable": False,
                  "naive_future": True, "naive_past": False, "null_start": False},
    "joined": {"upcoming": True, "past": False, "cancelled": True, "removed": True,
               "starting_now": True, "unparsable": False,
               "naive_future": True, "naive_past": False, "null_start": False},
}
CASES = [(role, state) for role in ("organized", "joined") for state in STATES]


def _seed_matrix(db, role, state):
    start, status, removed_at = STATES[state]
    db.tables["events"] = []
    db.tables["event_participants"] = []
    ev = _event("00000000-0000-4000-8000-00000000aaaa", "Case", TOM if role == "organized" else ANA)
    ev.update(start_datetime=start, status=status, removed_at=removed_at)
    db.tables["events"].append(ev)
    if role == "joined":
        db.tables["event_participants"].append({"id": 1, "event_id": ev["id"], "user_id": TOM, "status": "going"})


def _acted():
    cancelled, removed = admin_service.end_upcoming_activity(TOM, "reason", "Event '{title}' cancelled")
    return cancelled + removed > 0


@pytest.mark.parametrize("role,state", CASES, ids=[f"{r}-{s}" for r, s in CASES])
def test_helper_agrees_with_what_end_upcoming_activity_does(db, frozen_now, role, state):
    _seed_matrix(db, role, state)
    before = copy.deepcopy(db.tables)
    pending = suspension_service.has_pending_suspension_effects(TOM)
    assert db.tables == before, "the helper must be read-only"
    acted = _acted()
    assert acted is EXPECTED[role][state], "the case table no longer describes end_upcoming_activity"
    assert pending is acted


def test_helper_is_false_for_a_user_without_any_events(db, frozen_now):
    db.tables["events"], db.tables["event_participants"] = [], []
    assert suspension_service.has_pending_suspension_effects(TOM) is False
    assert _acted() is False


def test_helper_ignores_other_peoples_events(db, frozen_now):
    """ANA's upcoming event, where TOM did not join, is nobody's business here."""
    db.tables["event_participants"] = []
    assert _event_row(db, EV2)["created_by"] == ANA
    assert suspension_service.has_pending_suspension_effects(TOM) is True       # EV1 is TOM's own
    db.tables["events"] = [e for e in db.tables["events"] if e["created_by"] != TOM]
    assert suspension_service.has_pending_suspension_effects(TOM) is False
    assert _acted() is False
