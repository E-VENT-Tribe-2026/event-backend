"""Ticket #256: a removal whose owner notification or audit entry failed must be finishable.

Today those two steps swallow their failure: the endpoint answers 200 and a retry is refused with
409 already_removed, so the missing records are never created. Decided behaviour pinned here:

  * the removal and the warning stay, EVERY step is still attempted (participants are told inline) and the
    answer is the coded 503 removal_followups_incomplete {code, message, missing, event_id[, message_id]};
  * the same request again (content removed, steps missing) creates only the missing steps and answers 200
    with the normal body (original removed_at / removed_by, the existing warning); a finished removal and
    hard-deleted content are still refused;
  * a recovered audit entry names the ORIGINAL remover and carries retried:True (completed_by:<admin> when
    another administrator finished it);
  * content_removal_service.pending_removal_steps(kind, content_id) tells what is missing, writing nothing;
  * through a report the failed attempt reopens the report and the retry closes it with ONE report_action_taken.

Two worlds, both real services on the in-memory fake: the removal world of tests/test_content_removal.py
(`db`, routes /api/admin/events/...: ORG organizes EVENT, P1 / P2 joined it, P2 wrote "you are all ...") and the
report world of tests/test_admin_reports_actions.py (`rdb`: TOM owns EV1 and message MSG).
Every injected failure asserts that it was really hit. The fake enforces no unique keys, so rows are counted.
"""
import copy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.core.dependencies import require_admin
from app.main import app
from app.services import content_removal_service
from tests import test_admin_reports_actions as ra
from tests.test_admin_reports_action_failures import (  # noqa: F401  (inject is a fixture)
    _undo_update, _warnings_insert, inject,
)
from tests.test_content_removal import (  # noqa: F401  (db is a fixture, client drives the removal routes)
    ADMIN, ADMIN2, EVENT, OTHER_EVENT, ORG, P1, P2, client, code, current, db, msg, notes, remove_event,
    remove_message,
)

KINDS = ["event", "message"]
OWNER = {"event": ORG, "message": P2}
AUDIT_TYPE = {"event": "event_removed", "message": "message_removed"}
ENTITY = {"event": "event", "message": "chat_message"}
SUCCESS_KEYS = {"event": {"event_id", "is_removed", "removed_at", "removed_by", "report_id", "warning_id"},
                "message": {"event_id", "message_id", "is_removed", "removed_at", "removed_by", "report_id",
                            "warning_id"}}


# ---- removal world: helpers ----------------------------------------------------------------------

def content_id(db, kind):
    return EVENT if kind == "event" else msg(db, "you are all")["id"]


def row_of(db, kind):
    if kind == "event":
        return next(e for e in db.tables["events"] if e["id"] == EVENT)
    return msg(db, "you are all")


def remove(db, kind, **body):
    if kind == "event":
        return remove_event(**body)
    return remove_message(content_id(db, kind), **body)


def audit_rows(db, kind, cid=None):
    cid = content_id(db, kind) if cid is None else cid
    return [l for l in db.tables["logs"] if l["type"] == AUDIT_TYPE[kind]
            and l["entity_type"] == ENTITY[kind] and l["entity_id"] == str(cid)]


def owner_notices(db, kind):
    return notes(db, OWNER[kind], "content_removed")


def participant_notices(db):
    return {u: len(notes(db, u, "event_removed")) for u in (P1, P2)}


def values_of(entry):
    """The audit `values` tokens ("key:value") as an exact dict."""
    return dict(token.split(":", 1) for token in entry["values"])


def snapshot(db):
    return copy.deepcopy(db.tables)


def _notice_insert(q):
    return (q.name == "notifications" and q.action == "insert"
            and (q.payload or {}).get("type") == "content_removed")


def _audit_insert(type_):
    return lambda q: q.name == "logs" and q.action == "insert" and (q.payload or {}).get("type") == type_


def fail_notice(inject, **kw):
    return inject(_notice_insert, RuntimeError("notifications are down"), **kw)


def fail_audit(inject, kind, **kw):
    return inject(_audit_insert(AUDIT_TYPE[kind]), RuntimeError("logs are down"), **kw)


def assert_503(r, kind, db, missing):
    assert r.status_code == 503, r.text
    detail = r.json()["detail"]
    assert isinstance(detail, dict), detail
    assert detail["code"] == "removal_followups_incomplete"
    assert isinstance(detail["message"], str) and "removed" in detail["message"].lower()
    assert detail["missing"] == missing
    assert detail["event_id"] == EVENT
    if kind == "message":
        assert detail["message_id"] == content_id(db, kind)
    else:
        assert "message_id" not in detail


def assert_kept(db, kind, remover=ADMIN):
    """The removal and its warning stand after a failed follow-up."""
    row = row_of(db, kind)
    assert row["removed_at"] and row["removed_by"] == remover
    assert len(db.tables["warnings"]) == 1 and db.tables["warnings"][0]["user_id"] == OWNER[kind]


def assert_retry_body(r, kind, db, original_removed_at, remover=ADMIN):
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == SUCCESS_KEYS[kind]
    assert body["is_removed"] is True and body["removed_at"] == original_removed_at
    assert body["removed_by"]["id"] == remover
    assert body["report_id"] is None and body["warning_id"] == db.tables["warnings"][0]["id"]


# ==== 1. the owner notification fails ==============================================================

@pytest.mark.parametrize("kind", KINDS)
def test_failed_owner_notification_is_503_then_the_retry_completes_it(db, inject, kind):
    rule = fail_notice(inject)
    r = remove(db, kind)
    assert rule.hits == 1, "the notification failure was never injected"
    assert_503(r, kind, db, ["owner_notification"])
    assert_kept(db, kind)
    removed_at = row_of(db, kind)["removed_at"]
    assert owner_notices(db, kind) == []
    [entry] = audit_rows(db, kind)
    assert entry["created_by_id"] == ADMIN and "retried" not in values_of(entry)   # a first-attempt audit
    if kind == "event":
        assert participant_notices(db) == {P1: 1, P2: 1}      # told inline, before the error was raised

    retry = remove(db, kind)
    assert_retry_body(retry, kind, db, removed_at)
    [notice] = owner_notices(db, kind)
    assert notice["warning_id"] == db.tables["warnings"][0]["id"] and notice["event_id"] == EVENT
    assert len(db.tables["warnings"]) == 1
    assert len(audit_rows(db, kind)) == 1                    # the audit entry existed: not written again
    assert row_of(db, kind)["removed_at"] == removed_at
    if kind == "event":
        assert participant_notices(db) == {P1: 1, P2: 1}      # not told a second time
    assert remove(db, kind).status_code == 409               # now it is finished


# ==== 2. the audit entry fails =====================================================================

@pytest.mark.parametrize("kind", KINDS)
def test_failed_audit_entry_is_503_then_the_retry_records_it_for_the_original_remover(db, inject, kind):
    rule = fail_audit(inject, kind)
    r = remove(db, kind)
    assert rule.hits == 1, "the audit failure was never injected"
    assert_503(r, kind, db, ["audit_entry"])
    assert_kept(db, kind)
    removed_at = row_of(db, kind)["removed_at"]
    assert audit_rows(db, kind) == [] and len(owner_notices(db, kind)) == 1
    if kind == "event":
        assert participant_notices(db) == {P1: 1, P2: 1}
    recovered_after = datetime.now(timezone.utc)

    retry = remove(db, kind)
    assert_retry_body(retry, kind, db, removed_at)
    [entry] = audit_rows(db, kind)
    assert entry["created_by_id"] == ADMIN
    values = values_of(entry)
    assert values["retried"] == "True" and "completed_by" not in values   # same person: nothing to add
    assert datetime.fromisoformat(entry["created_date"]) >= recovered_after   # the time of recovery
    assert len(owner_notices(db, kind)) == 1 and len(db.tables["warnings"]) == 1
    if kind == "event":
        assert participant_notices(db) == {P1: 1, P2: 1}


# ==== 3. both fail ==================================================================================

@pytest.mark.parametrize("kind", KINDS)
def test_both_failing_gives_one_503_listing_both_and_the_retry_completes_both_once(db, inject, kind):
    notice, audit = fail_notice(inject), fail_audit(inject, kind)
    r = remove(db, kind)
    assert notice.hits == 1 and audit.hits == 1, "a failure was never injected"
    assert_503(r, kind, db, ["owner_notification", "audit_entry"])
    assert_kept(db, kind)
    assert owner_notices(db, kind) == [] and audit_rows(db, kind) == []
    if kind == "event":
        assert participant_notices(db) == {P1: 1, P2: 1}    # every step was still attempted

    retry = remove(db, kind)
    assert_retry_body(retry, kind, db, row_of(db, kind)["removed_at"])
    assert len(owner_notices(db, kind)) == 1 and len(audit_rows(db, kind)) == 1
    assert values_of(audit_rows(db, kind)[0])["retried"] == "True"
    assert len(db.tables["warnings"]) == 1
    if kind == "event":
        assert participant_notices(db) == {P1: 1, P2: 1}


# ==== 4. a second failure on the retry =============================================================

@pytest.mark.parametrize("kind", KINDS)
def test_the_retry_failing_again_is_503_again_and_the_third_attempt_completes(db, inject, kind):
    notice = fail_notice(inject, times=2)
    audit = fail_audit(inject, kind, times=2)
    first = remove(db, kind)
    assert_503(first, kind, db, ["owner_notification", "audit_entry"])
    second = remove(db, kind)
    assert notice.hits == 2 and audit.hits == 2, "the retry did not try both missing steps"
    assert_503(second, kind, db, ["owner_notification", "audit_entry"])
    assert owner_notices(db, kind) == [] and audit_rows(db, kind) == []

    third = remove(db, kind)
    assert_retry_body(third, kind, db, row_of(db, kind)["removed_at"])
    assert len(owner_notices(db, kind)) == 1 and len(audit_rows(db, kind)) == 1
    assert len(db.tables["warnings"]) == 1
    if kind == "event":
        assert participant_notices(db) == {P1: 1, P2: 1}    # only the first attempt told them


@pytest.mark.parametrize("kind", KINDS)
def test_a_retry_that_fixes_one_step_and_fails_the_other_names_only_the_missing_one(db, inject, kind):
    fail_notice(inject)
    fail_audit(inject, kind, times=2)
    assert_503(remove(db, kind), kind, db, ["owner_notification", "audit_entry"])
    second = remove(db, kind)                                 # the notification works now, the audit does not
    assert_503(second, kind, db, ["audit_entry"])
    assert len(owner_notices(db, kind)) == 1 and audit_rows(db, kind) == []
    assert remove(db, kind).status_code == 200
    assert len(owner_notices(db, kind)) == 1 and len(audit_rows(db, kind)) == 1


# ==== 5. finished or hard-deleted content ==========================================================

@pytest.mark.parametrize("kind", KINDS)
def test_a_finished_removal_is_still_409_and_writes_nothing(db, kind):
    assert remove(db, kind).status_code == 200
    before = snapshot(db)
    r = remove(db, kind)
    assert r.status_code == 409 and code(r) == "already_removed"
    assert snapshot(db) == before


@pytest.mark.parametrize("kind", KINDS)
def test_hard_deleted_content_is_refused_and_writes_nothing(db, inject, kind):
    """The row is gone (not just marked): the service answers 404 as it always did (see the report)."""
    fail_notice(inject)
    assert remove(db, kind).status_code == 503
    cid = content_id(db, kind)
    if kind == "event":
        db.tables["events"] = [e for e in db.tables["events"] if e["id"] != EVENT]
    else:
        db.tables["event_chats"] = [m for m in db.tables["event_chats"] if m["id"] != cid]
    before = snapshot(db)
    r = remove_event() if kind == "event" else remove_message(cid)
    assert r.status_code == 404 and code(r) == f"{kind}_not_found"
    assert snapshot(db) == before


# ==== 6. identity edges ============================================================================

@pytest.mark.parametrize("kind", KINDS)
def test_a_warned_owner_is_matched_by_the_warning_id_not_by_other_notices(db, inject, kind):
    decoy = db.add("notifications", {"user_id": OWNER[kind], "event_id": EVENT, "type": "content_removed",
                                     "message": "Your content was removed. Something older.", "is_read": True,
                                     "warning_id": 9999})
    fail_notice(inject)
    assert_503(remove(db, kind), kind, db, ["owner_notification"])
    assert remove(db, kind).status_code == 200
    warning_id = db.tables["warnings"][0]["id"]
    assert [n["warning_id"] for n in owner_notices(db, kind)].count(warning_id) == 1
    assert decoy in owner_notices(db, kind) and len(owner_notices(db, kind)) == 2


@pytest.mark.parametrize("kind", KINDS)
def test_an_administrator_owner_without_a_warning_is_matched_by_user_type_event_and_text(db, inject, kind):
    next(p for p in db.tables["profiles"] if p["id"] == OWNER[kind])["role"] = "administrator"
    decoy = db.add("notifications", {"user_id": OWNER[kind], "event_id": EVENT, "type": "content_removed",
                                     "message": "Your content was removed. Another text.", "is_read": True,
                                     "warning_id": None})
    fail_notice(inject)
    assert_503(remove(db, kind), kind, db, ["owner_notification"])      # the other text is no match
    assert db.tables["warnings"] == [] and owner_notices(db, kind) == [decoy]
    assert remove(db, kind).status_code == 200
    created = [n for n in owner_notices(db, kind) if n is not decoy]
    assert len(created) == 1 and created[0]["warning_id"] is None
    assert len(audit_rows(db, kind)) == 1
    before = snapshot(db)
    r = remove(db, kind)                                                 # the exact text is found now
    assert r.status_code == 409 and snapshot(db) == before


@pytest.mark.parametrize("first", KINDS)
def test_an_event_removal_and_a_message_removal_in_one_event_do_not_mask_each_other(db, inject, first):
    """ORG organizes EVENT and also wrote a message in it: one owner, one event, two removals."""
    sent = db.add("event_chats", {"event_id": EVENT, "sender_id": ORG, "type": "chat", "content": "org speaks"})
    ops = {"event": lambda: remove_event(), "message": lambda: remove_message(sent["id"])}
    second = "message" if first == "event" else "event"
    assert ops[first]().status_code == 200
    rule = fail_notice(inject)
    r = ops[second]()
    assert rule.hits == 1
    assert r.status_code == 503 and r.json()["detail"]["missing"] == ["owner_notification"]
    assert ops[second]().status_code == 200
    notices = notes(db, ORG, "content_removed")
    assert len(notices) == 2 and len({n["warning_id"] for n in notices}) == 2
    assert len(db.tables["warnings"]) == 2
    assert len(audit_rows(db, "event")) == 1 and len(audit_rows(db, "message", sent["id"])) == 1


def test_two_identical_messages_removed_separately_each_get_their_own_notification(db):
    first = db.add("event_chats", {"event_id": EVENT, "sender_id": P1, "type": "chat", "content": "same words"})
    second = db.add("event_chats", {"event_id": EVENT, "sender_id": P1, "type": "chat", "content": "same words"})
    assert remove_message(first["id"]).status_code == 200
    assert remove_message(second["id"]).status_code == 200
    notices = notes(db, P1, "content_removed")
    assert len(notices) == 2 and len({n["warning_id"] for n in notices}) == 2
    assert len(audit_rows(db, "message", first["id"])) == 1 and len(audit_rows(db, "message", second["id"])) == 1


def test_a_failed_notification_of_the_second_identical_message_is_not_masked_by_the_first(db, inject):
    first = db.add("event_chats", {"event_id": EVENT, "sender_id": P1, "type": "chat", "content": "same words"})
    second = db.add("event_chats", {"event_id": EVENT, "sender_id": P1, "type": "chat", "content": "same words"})
    assert remove_message(first["id"]).status_code == 200
    fail_notice(inject)
    r = remove_message(second["id"])
    assert r.status_code == 503 and r.json()["detail"]["missing"] == ["owner_notification"]
    assert remove_message(second["id"]).status_code == 200
    assert len(notes(db, P1, "content_removed")) == 2


@pytest.mark.parametrize("kind", KINDS)
def test_a_notification_the_owner_deleted_counts_as_missing_and_is_recreated(db, kind):
    """Documented edge: after a complete removal the owner deletes the notification; a repeated request is not a
    409 but recreates it (the warning and the audit entry are not touched)."""
    assert remove(db, kind).status_code == 200
    removed_at = row_of(db, kind)["removed_at"]
    db.tables["notifications"] = [n for n in db.tables["notifications"] if n["type"] != "content_removed"]
    retry = remove(db, kind)
    assert_retry_body(retry, kind, db, removed_at)
    assert len(owner_notices(db, kind)) == 1
    assert len(db.tables["warnings"]) == 1 and len(audit_rows(db, kind)) == 1
    assert "retried" not in values_of(audit_rows(db, kind)[0])


# ==== 7. a retry by another administrator ==========================================================

@pytest.mark.parametrize("kind", KINDS)
def test_another_administrator_finishing_it_is_named_but_the_original_remover_stays(db, inject, kind):
    fail_audit(inject, kind)
    assert_503(remove(db, kind), kind, db, ["audit_entry"])
    removed_at = row_of(db, kind)["removed_at"]
    current["id"] = ADMIN2
    retry = remove(db, kind)
    assert_retry_body(retry, kind, db, removed_at, remover=ADMIN)       # removed_by is the original remover
    assert row_of(db, kind)["removed_by"] == ADMIN
    [entry] = audit_rows(db, kind)
    assert entry["created_by_id"] == ADMIN
    values = values_of(entry)
    assert values["retried"] == "True" and values["completed_by"] == ADMIN2
    assert len(db.tables["warnings"]) == 1 and db.tables["warnings"][0]["admin_id"] == ADMIN


# ==== 8. the helper ================================================================================

def pending(db, kind):
    return content_removal_service.pending_removal_steps(kind, content_id(db, kind))


@pytest.mark.parametrize("kind", KINDS)
def test_pending_steps_of_content_that_is_not_removed_is_empty_and_writes_nothing(db, kind):
    before = snapshot(db)
    assert pending(db, kind) == []
    assert snapshot(db) == before


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("notice_fails, audit_fails, expected", [
    (False, False, []),
    (True, False, ["owner_notification"]),
    (False, True, ["audit_entry"]),
    (True, True, ["owner_notification", "audit_entry"]),
])
def test_pending_steps_match_what_the_service_left_undone(db, inject, kind, notice_fails, audit_fails, expected):
    rules = []
    if notice_fails:
        rules.append(fail_notice(inject))
    if audit_fails:
        rules.append(fail_audit(inject, kind))
    r = remove(db, kind)
    assert all(rule.hits == 1 for rule in rules)
    assert r.status_code == (503 if expected else 200)
    before = snapshot(db)
    assert pending(db, kind) == expected
    assert snapshot(db) == before                              # read only
    if expected:
        assert remove(db, kind).status_code == 200
        assert pending(db, kind) == []


@pytest.mark.parametrize("kind", KINDS)
def test_pending_steps_of_hard_deleted_or_unknown_content_is_empty(db, inject, kind):
    fail_notice(inject)
    fail_audit(inject, kind)
    assert remove(db, kind).status_code == 503
    cid = content_id(db, kind)
    assert pending(db, kind) == ["owner_notification", "audit_entry"]
    if kind == "event":
        db.tables["events"] = [e for e in db.tables["events"] if e["id"] != EVENT]
        unknown = "99999999-9999-4999-8999-999999999999"
    else:
        db.tables["event_chats"] = [m for m in db.tables["event_chats"] if m["id"] != cid]
        unknown = 99999
    before = snapshot(db)
    assert content_removal_service.pending_removal_steps(kind, cid) == []
    assert content_removal_service.pending_removal_steps(kind, unknown) == []
    assert snapshot(db) == before


# ==== 9. body shapes ===============================================================================

@pytest.mark.parametrize("kind", KINDS)
def test_503_body_has_exactly_the_documented_fields(db, inject, kind):
    fail_notice(inject)
    fail_audit(inject, kind)
    r = remove(db, kind)
    assert r.status_code == 503, r.text
    detail = r.json()["detail"]
    assert set(detail) == ({"code", "message", "missing", "event_id"} | ({"message_id"} if kind == "message" else set()))
    assert_503(r, kind, db, ["owner_notification", "audit_entry"])


@pytest.mark.parametrize("kind", KINDS)
def test_the_200_body_of_a_recovery_has_the_keys_of_a_normal_success(db, inject, kind):
    if kind == "event":
        normal = remove_event(OTHER_EVENT)
    else:
        normal = remove_message(msg(db, "hello all")["id"])
    assert normal.status_code == 200 and set(normal.json()) == SUCCESS_KEYS[kind]
    fail_notice(inject)
    assert remove(db, kind).status_code == 503
    assert set(remove(db, kind).json()) == set(normal.json()) == SUCCESS_KEYS[kind]


# ==== 10. through a report =========================================================================

@pytest.fixture
def rdb():
    """The report world (TOM organizes EV1 and wrote message MSG in it; ADM is assigned to every report)."""
    fake = ra._build_fake()
    with ra._patched(fake):
        app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id=ra.ADM)
        yield fake
        app.dependency_overrides.clear()


R_AUDIT = {"event": "event_removed", "message": "message_removed"}
R_CONTENT = {"event": ra.EV1, "message": ra.MSG}
R_MISSING = {"notice": ["owner_notification"], "audit": ["audit_entry"],
             "both": ["owner_notification", "audit_entry"]}


def r_row(rdb, kind):
    return ra._event_row(rdb) if kind == "event" else ra._chat_row(rdb)


def r_audit(rdb, kind):
    return [l for l in rdb.tables["logs"] if l["type"] == R_AUDIT[kind]]


def r_notices(rdb):
    return [n for n in rdb.tables["notifications"] if n["type"] == "content_removed" and n["user_id"] == ra.TOM]


def r_participants(rdb):
    return {u: len([n for n in rdb.tables["notifications"] if n["type"] == "event_removed" and n["user_id"] == u])
            for u in (ra.MIA, ra.ANA)}


def r_fail(inject, kind, which):
    rules = []
    if which in ("notice", "both"):
        rules.append(inject(_notice_insert, RuntimeError("notifications are down")))
    if which in ("audit", "both"):
        rules.append(inject(_audit_insert(R_AUDIT[kind]), RuntimeError("logs are down")))
    return rules


def r_failed_attempt(rdb, inject, kind, which, rid=1):
    ra._seed(rdb, kind, rid)
    rules = r_fail(inject, kind, which)
    res = ra._act(rid, action="remove_content", reason=None)
    assert all(rule.hits == 1 for rule in rules), "a failure was never injected"
    assert res.status_code == 503, res.text
    detail = res.json()["detail"]
    assert detail["code"] == "removal_followups_incomplete" and detail["missing"] == R_MISSING[which]
    assert detail["event_id"] == ra.EV1
    assert (detail.get("message_id") == ra.MSG) if kind == "message" else "message_id" not in detail
    # the report is reopened, assignee kept, nothing of the failed attempt is left on it
    ra._assert_open_unchanged(rdb, rid)
    assert ra._row(rdb, rid)["assigned_to"] == ra.ADM
    assert ra._report_logs(rdb) == []                          # no report_action_taken from the failed attempt
    # the removal and the warning stay
    assert r_row(rdb, kind)["removed_at"] and r_row(rdb, kind)["removed_by"] == ra.ADM
    assert [w["user_id"] for w in ra._warnings(rdb)] == [ra.TOM]
    if kind == "event":
        assert r_participants(rdb) == {ra.MIA: 1, ra.ANA: 1}   # told inline


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("which", ["notice", "audit", "both"])
@pytest.mark.parametrize("retrier", ["same_admin", "other_admin"])
def test_a_failed_followup_through_a_report_reopens_it_and_the_retry_closes_it(rdb, inject, kind, which, retrier):
    r_failed_attempt(rdb, inject, kind, which)
    removed_at = r_row(rdb, kind)["removed_at"]
    admin = ra.ADM
    if retrier == "other_admin":
        admin = ra.ADM2
        ra._row(rdb)["assigned_to"] = ra.ADM2
        app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id=ra.ADM2)

    res = ra._act(action="remove_content", reason=None)
    ra._assert_closed_response(rdb, res, 1, "resolved", "content_removed", admin=admin)
    assert ra._row(rdb)["closed_at"] is not None
    ra._assert_closure_audit(rdb, 1, "report_action_taken", "content_removed", admin=admin)   # exactly one
    assert r_row(rdb, kind)["removed_at"] == removed_at and r_row(rdb, kind)["removed_by"] == ra.ADM
    assert len(ra._warnings(rdb)) == 1 and len(r_notices(rdb)) == 1
    [entry] = r_audit(rdb, kind)
    values = ra_values(entry)
    assert entry["created_by_id"] == ra.ADM and values["report_id"] == "1"
    if which == "notice":
        assert "retried" not in values                          # the first attempt's own audit entry
    else:
        assert values["retried"] == "True"
        assert values.get("completed_by") == (ra.ADM2 if retrier == "other_admin" else None)
    if kind == "event":
        assert r_participants(rdb) == {ra.MIA: 1, ra.ANA: 1}


def ra_values(entry):
    return dict(token.split(":", 1) for token in entry["values"])


@pytest.mark.parametrize("kind", KINDS)
def test_a_genuine_duplicate_removal_through_a_report_is_409_and_leaves_the_report_unclaimed(rdb, kind):
    ra._seed(rdb, kind)
    ra._complete_removal(rdb, kind)
    before = ra._snapshot(rdb)
    res = ra._act(action="remove_content", reason=None)
    assert res.status_code == 409 and ra._code(res) == "already_removed"
    assert ra._snapshot(rdb) == before
    ra._assert_open_unchanged(rdb)
    assert ra._row(rdb)["assigned_to"] == ra.ADM


@pytest.mark.parametrize("kind", KINDS)
def test_hard_deleted_content_with_missing_steps_is_409_through_a_report_and_nothing_is_claimed(rdb, inject, kind):
    r_failed_attempt(rdb, inject, kind, "notice")
    if kind == "event":
        rdb.tables["events"] = [e for e in rdb.tables["events"] if e["id"] != ra.EV1]
    else:
        rdb.tables["event_chats"] = [m for m in rdb.tables["event_chats"] if m["id"] != ra.MSG]
    before = ra._snapshot(rdb)
    res = ra._act(action="remove_content", reason=None)
    assert res.status_code == 409 and ra._code(res) == "already_removed"
    assert ra._snapshot(rdb) == before
    ra._assert_open_unchanged(rdb)


@pytest.mark.parametrize("kind", KINDS)
def test_a_report_retry_that_fails_again_is_503_again_and_reopened_again(rdb, inject, kind):
    r_failed_attempt(rdb, inject, kind, "notice")
    again = inject(_notice_insert, RuntimeError("still down"))
    res = ra._act(action="remove_content", reason=None)
    assert again.hits == 1
    assert res.status_code == 503 and ra._code(res) == "removal_followups_incomplete"
    ra._assert_open_unchanged(rdb)
    assert ra._report_logs(rdb) == [] and r_notices(rdb) == []
    done = ra._act(action="remove_content", reason=None)
    ra._assert_closed_response(rdb, done, 1, "resolved", "content_removed")
    ra._assert_closure_audit(rdb, 1, "report_action_taken", "content_removed")
    assert len(r_notices(rdb)) == 1 and len(ra._warnings(rdb)) == 1 and len(r_audit(rdb, kind)) == 1


@pytest.mark.parametrize("kind", KINDS)
def test_removal_incomplete_still_keeps_the_report_closed(rdb, inject, kind):
    """Smoke check of the unchanged behaviour (full assertions: test_admin_reports_action_failures.py)."""
    ra._seed(rdb, kind)
    table = "events" if kind == "event" else "event_chats"
    warning = inject(_warnings_insert, RuntimeError("warnings are down"), times=None)
    undo = inject(_undo_update(table), RuntimeError("db down"))
    res = ra._act(action="remove_content", reason=None)
    assert warning.hits >= 1 and undo.hits == 1
    assert res.status_code == 500 and res.json()["detail"]["code"] == "removal_incomplete"
    row = ra._row(rdb)
    assert (row["status"], row["outcome"], row["closed_by"]) == ("resolved", "content_removed", ra.ADM)


# ==== 11. review fixes F-001 .. F-009 ==================================================================

from fastapi.testclient import TestClient  # noqa: E402

from app.services import audit_service  # noqa: E402
from tests._fake_supabase import FakeSupabase  # noqa: E402

quiet = TestClient(app, raise_server_exceptions=False)   # an uncoded 500 stays a response
SUFFIX = " This counts as a warning."


def legacy_texts(db, kind):
    """The notification text of a removal as stored before #255 (with the warning suffix)."""
    if kind == "event":
        return 'Your content was removed. Your event "Sunset Picnic" was removed by an administrator.' + SUFFIX
    snippet = content_removal_service._snippet(row_of(db, "message")["content"])
    return ('Your content was removed. Your message in "Sunset Picnic" was removed by an administrator: '
            f'"{snippet}".' + SUFFIX)


def seed_legacy_removal(db, kind, notice=True, audit=True):
    """A removal from before #255: removed row, a warning WITHOUT removal_key, the notification with the warning
    suffix and its warning_id, and the audit entry."""
    row = row_of(db, kind)
    row.update(removed_at="2026-01-01T00:00:00+00:00", removed_by=ADMIN)
    about_type = "event" if kind == "event" else "chat_message"
    warning = db.add("warnings", {"user_id": OWNER[kind], "admin_id": ADMIN, "reason": "old",
                                  "about_type": about_type, "about_id": str(row["id"])})
    assert "removal_key" not in warning
    if notice:
        db.add("notifications", {"user_id": OWNER[kind], "event_id": EVENT, "type": "content_removed",
                                 "message": legacy_texts(db, kind), "is_read": False, "warning_id": warning["id"]})
    if audit:
        db.add("logs", {"type": AUDIT_TYPE[kind], "created_by_id": ADMIN, "entity_type": ENTITY[kind],
                        "entity_id": str(row["id"]), "description": "removed", "values": []})
    return warning


def make_incomplete(db, inject, kind):
    """removal_incomplete: the warning insert fails AND the undo fails (removed, no warning, no records)."""
    table = "events" if kind == "event" else "event_chats"
    warning = inject(_warnings_insert, RuntimeError("warnings are down"))
    undo = inject(_undo_update(table), RuntimeError("db down"))
    r = remove(db, kind)
    assert warning.hits == 1 and undo.hits == 1
    assert r.status_code == 500 and code(r) == "removal_incomplete"
    assert row_of(db, kind)["removed_at"]
    assert db.tables["warnings"] == [] and owner_notices(db, kind) == [] and audit_rows(db, kind) == []


# ---- F-001: a removal from before #255 is finished -----------------------------------------------

@pytest.mark.parametrize("kind", KINDS)
def test_a_legacy_removal_with_an_unkeyed_warning_and_suffixed_notice_is_still_409(db, kind):
    seed_legacy_removal(db, kind)
    assert pending(db, kind) == []
    before = snapshot(db)
    r = remove(db, kind)
    assert r.status_code == 409 and code(r) == "already_removed"
    assert snapshot(db) == before


@pytest.mark.parametrize("kind", KINDS)
def test_a_second_report_about_a_legacy_removal_is_409_and_claims_nothing(rdb, kind):
    ra._seed(rdb, kind)
    ra._complete_removal(rdb, kind)
    for w in rdb.tables["warnings"]:
        w.pop("removal_key")
    parts = content_removal_service._owner_notice_parts(kind, r_row(rdb, kind), "Board game night")
    for n in rdb.tables["notifications"]:
        n["message"] = content_removal_service._owner_message(parts[2], True, parts[3])
    before = ra._snapshot(rdb)
    res = ra._act(action="remove_content", reason=None)
    assert res.status_code == 409 and ra._code(res) == "already_removed"
    assert ra._snapshot(rdb) == before


# ---- F-002: a removal_incomplete one is finished with its warning ---------------------------------

@pytest.mark.parametrize("kind", KINDS)
def test_a_retry_after_removal_incomplete_gives_the_warning_the_notice_and_one_audit_entry(db, inject, kind):
    make_incomplete(db, inject, kind)
    removed_at = row_of(db, kind)["removed_at"]
    assert pending(db, kind) == ["owner_notification", "audit_entry"]
    r = remove(db, kind)
    assert_retry_body(r, kind, db, removed_at)
    [warning] = db.tables["warnings"]
    assert warning["user_id"] == OWNER[kind] and warning["removal_key"].endswith(str(content_id(db, kind)))
    [notice] = owner_notices(db, kind)
    assert notice["warning_id"] == warning["id"] and notice["message"].endswith(SUFFIX)
    [entry] = audit_rows(db, kind)
    assert values_of(entry)["warning_id"] == str(warning["id"]) and values_of(entry)["retried"] == "True"
    assert pending(db, kind) == []
    assert remove(db, kind).status_code == 409


@pytest.mark.parametrize("kind", KINDS)
def test_a_retry_whose_warning_fails_again_is_removal_incomplete_and_writes_nothing_else(db, inject, kind):
    make_incomplete(db, inject, kind)
    again = inject(_warnings_insert, RuntimeError("still down"))
    before = snapshot(db)
    r = remove(db, kind)
    assert again.hits == 1
    assert r.status_code == 500 and code(r) == "removal_incomplete"
    assert snapshot(db) == before
    assert remove(db, kind).status_code == 200          # and the next one completes it


@pytest.mark.parametrize("kind", KINDS)
def test_a_legacy_removal_with_a_lost_audit_entry_gets_no_second_warning(db, kind):
    legacy = seed_legacy_removal(db, kind, audit=False)
    assert pending(db, kind) == ["audit_entry"]
    r = remove(db, kind)
    assert r.status_code == 200
    assert db.tables["warnings"] == [legacy]
    assert len(owner_notices(db, kind)) == 1 and len(audit_rows(db, kind)) == 1


# ---- F-003: the retry re-reads the mark ----------------------------------------------------------

@pytest.mark.parametrize("kind", KINDS)
def test_a_retry_whose_mark_vanished_meanwhile_is_409_and_writes_nothing(db, inject, monkeypatch, kind):
    fail_notice(inject)
    fail_audit(inject, kind)
    assert remove(db, kind).status_code == 503
    row = row_of(db, kind)
    real = content_removal_service._removal_row
    calls = {"n": 0}

    def hooked(k, cid):
        calls["n"] += 1
        if calls["n"] == 2:                       # 1: pending_removal_steps, 2: the guard in the recovery
            row.update(removed_at=None, removed_by=None)   # the first request undid its mark
        return real(k, cid)

    monkeypatch.setattr(content_removal_service, "_removal_row", hooked)
    before = snapshot(db)
    r = remove(db, kind)
    assert calls["n"] >= 2
    assert r.status_code == 409 and code(r) == "already_removed"
    row_after = snapshot(db)
    assert row_after["notifications"] == before["notifications"] and row_after["logs"] == before["logs"]


# ---- F-004: a failing profile read cannot turn a done recovery into a 500 -------------------------

def _profiles_people_read(q):
    return q.name == "profiles" and q.action == "select" and "username" in q.cols


@pytest.mark.parametrize("kind", KINDS)
def test_a_failing_profile_read_during_a_recovery_is_still_200_with_the_records_written_once(db, inject, kind):
    fail_notice(inject)
    fail_audit(inject, kind)
    assert remove(db, kind).status_code == 503
    people = inject(_profiles_people_read, RuntimeError("profiles are down"), times=None)
    r = remove(db, kind)
    assert people.hits >= 1
    assert r.status_code == 200, r.text
    assert r.json()["removed_by"] is None and r.json()["warning_id"] == db.tables["warnings"][0]["id"]
    assert len(owner_notices(db, kind)) == 1 and len(audit_rows(db, kind)) == 1
    assert len(db.tables["warnings"]) == 1


@pytest.mark.parametrize("kind", KINDS)
def test_a_failing_profile_read_during_a_report_recovery_still_closes_the_report(rdb, inject, kind):
    r_failed_attempt(rdb, inject, kind, "both")
    people = inject(_profiles_people_read, RuntimeError("profiles are down"), times=None)
    res = quiet.post("/api/admin/reports/1/action", json={"action": "remove_content"})
    assert people.hits >= 1
    assert res.status_code == 200, res.text
    row = ra._row(rdb)
    assert (row["status"], row["outcome"], row["closed_by"]) == ("resolved", "content_removed", ra.ADM)
    assert len(r_notices(rdb)) == 1 and len(r_audit(rdb, kind)) == 1 and len(ra._warnings(rdb)) == 1


# ---- F-005: a second report after the owner deleted the notifications -----------------------------

@pytest.mark.parametrize("kind", KINDS)
def test_a_second_report_after_the_owner_deleted_the_notifications_recreates_only_that(rdb, kind):
    ra._seed(rdb, kind)
    ra._complete_removal(rdb, kind)
    rdb.tables["notifications"] = [n for n in rdb.tables["notifications"] if n["type"] != "content_removed"]
    res = ra._act(action="remove_content", reason=None)
    ra._assert_closed_response(rdb, res, 1, "resolved", "content_removed")
    ra._assert_closure_audit(rdb, 1, "report_action_taken", "content_removed")
    assert len(r_notices(rdb)) == 1 and len(ra._warnings(rdb)) == 1
    assert len(r_audit(rdb, kind)) == 1          # the audit entry was not missing, so none is added


# ---- F-006: a failing read is an uncoded 500 before any claim ------------------------------------

def _notifications_read(q):
    return q.name == "notifications" and q.action == "select"


@pytest.mark.parametrize("kind", KINDS)
def test_a_failing_pending_read_is_a_500_and_writes_nothing_standalone(db, inject, kind):
    assert remove(db, kind).status_code == 200
    rule = inject(_notifications_read, RuntimeError("notifications are down"), times=None)
    before = snapshot(db)
    url = (f"/api/admin/events/{EVENT}/remove" if kind == "event"
           else f"/api/admin/events/{EVENT}/messages/{content_id(db, kind)}/remove")
    r = quiet.post(url, headers={"Authorization": "Bearer token"})
    assert rule.hits >= 1 and r.status_code == 500
    assert snapshot(db) == before


@pytest.mark.parametrize("kind", KINDS)
def test_a_failing_pending_read_through_a_report_is_a_500_with_the_report_untouched(rdb, inject, kind):
    ra._seed(rdb, kind)
    ra._complete_removal(rdb, kind)
    rule = inject(_notifications_read, RuntimeError("notifications are down"), times=None)
    before = ra._snapshot(rdb)
    res = quiet.post("/api/admin/reports/1/action", json={"action": "remove_content"})
    assert rule.hits >= 1 and res.status_code == 500
    assert ra._snapshot(rdb) == before
    ra._assert_open_unchanged(rdb)


# ---- F-009: more edges ---------------------------------------------------------------------------

def test_record_audit_returns_true_on_success_false_on_failure_and_never_raises(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(audit_service, "supabase", fake)
    assert audit_service.record_audit("x", ADMIN, "event", "1", "d", {"a": 1}) is True
    assert len(fake.tables["logs"]) == 1

    class Broken:
        def table(self, name):
            raise RuntimeError("down")

    monkeypatch.setattr(audit_service, "supabase", Broken())
    assert audit_service.record_audit("x", ADMIN, "event", "1", "d") is False


@pytest.mark.parametrize("kind", KINDS)
def test_without_a_recorded_remover_the_recovery_falls_back_to_the_retrying_admin(db, inject, kind):
    fail_audit(inject, kind)
    assert remove(db, kind).status_code == 503
    row_of(db, kind)["removed_by"] = None
    current["id"] = ADMIN2
    r = remove(db, kind)
    assert r.status_code == 200 and r.json()["removed_by"]["id"] == ADMIN2
    [entry] = audit_rows(db, kind)
    assert entry["created_by_id"] == ADMIN2 and "completed_by" not in values_of(entry)


@pytest.mark.parametrize("kind", KINDS)
def test_a_recovery_with_a_wrong_or_unknown_report_writes_nothing(db, inject, kind):
    fail_audit(inject, kind)
    assert remove(db, kind).status_code == 503
    db.tables["reports"] = [{"id": 5, "target_type": "user", "event_id": None, "message_id": None}]
    before = snapshot(db)
    r = remove(db, kind, report_id=5)
    assert r.status_code == 400 and code(r) == "report_mismatch"
    r = remove(db, kind, report_id=999)
    assert r.status_code == 404 and code(r) == "report_not_found"
    assert snapshot(db) == before


def test_an_event_without_an_owner_has_only_the_audit_step_pending(db, inject):
    next(e for e in db.tables["events"] if e["id"] == EVENT)["created_by"] = None
    fail_audit(inject, "event")
    first = remove(db, "event")
    assert first.status_code == 503 and first.json()["detail"]["missing"] == ["audit_entry"]
    assert pending(db, "event") == ["audit_entry"]
    r = remove(db, "event")
    assert r.status_code == 200 and r.json()["warning_id"] is None
    assert db.tables["warnings"] == [] and notes(db, ORG, "content_removed") == []
    assert len(audit_rows(db, "event")) == 1


@pytest.mark.parametrize("kind", KINDS)
def test_an_owner_who_became_an_administrator_after_a_warned_removal_keeps_the_warning(db, inject, kind):
    fail_notice(inject)
    assert remove(db, kind).status_code == 503
    next(p for p in db.tables["profiles"] if p["id"] == OWNER[kind])["role"] = "administrator"
    removed_at = row_of(db, kind)["removed_at"]
    r = remove(db, kind)
    assert_retry_body(r, kind, db, removed_at)
    [notice] = owner_notices(db, kind)
    assert notice["warning_id"] == db.tables["warnings"][0]["id"]
    assert len(db.tables["warnings"]) == 1 and len(audit_rows(db, kind)) == 1


@pytest.mark.parametrize("kind", KINDS)
def test_a_retry_through_another_report_records_that_report_in_the_audit_entry(db, inject, kind):
    target = ({"target_type": "event", "event_id": EVENT, "message_id": None} if kind == "event"
              else {"target_type": "message", "event_id": EVENT, "message_id": content_id(db, kind)})
    db.tables["reports"] = [{"id": 1, **target}, {"id": 2, **target}]
    fail_audit(inject, kind)
    assert remove(db, kind, report_id=1).status_code == 503
    assert remove(db, kind, report_id=2).status_code == 200
    [entry] = audit_rows(db, kind)
    assert values_of(entry)["report_id"] == "2" and values_of(entry)["retried"] == "True"


def test_participants_are_not_notified_again_for_an_event_and_never_for_a_message(db, inject):
    fail_audit(inject, "event")
    assert remove(db, "event").status_code == 503
    assert participant_notices(db) == {P1: 1, P2: 1}
    assert remove(db, "event").status_code == 200
    assert participant_notices(db) == {P1: 1, P2: 1}

    fail_audit(inject, "message")
    assert remove(db, "message").status_code == 503
    assert remove(db, "message").status_code == 200
    assert participant_notices(db) == {P1: 1, P2: 1}     # a message removal never notifies participants
