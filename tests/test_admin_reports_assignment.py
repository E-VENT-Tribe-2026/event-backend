"""Report assignment: only the assignee may dismiss or act.

  POST /api/admin/reports/{id}/assign    {"admin_id": "<admin uuid>"}
  POST /api/admin/reports/{id}/unassign

List and detail carry assigned_to (PersonSummary or null). Dismiss / warn / remove / suspend
are 403 unless the caller is the assignee. Assignment is stored on the report row so every
administrator sees a claim, including over the existing reports realtime publication.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.core.dependencies import require_admin
from app.main import app
from tests import _fake_supabase
from tests.test_admin_reports_actions import (  # noqa: F401  (db fixture)
    ADM, ADM2, PERSON_KEYS, TOM, _act, _assert_open_unchanged, _assert_untouched, _build_user_summary,
    _code, _detail, _dismiss, _profile_row, _report_logs, _row, _seed, _snapshot, client, db,
)

MISSING = "00000000-0000-4000-8000-000000000000"


def _assign(rid=1, admin_id=ADM):
    return client.post(f"/api/admin/reports/{rid}/assign", json={"admin_id": admin_id})


def _unassign(rid=1):
    return client.post(f"/api/admin/reports/{rid}/unassign")


def _as(uid):
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id=uid)


def _person(db, uid):
    return _build_user_summary(_profile_row(db, uid))


def _assert_assigned(db, uid, rid=1, body=None):
    assert _row(db, rid)["assigned_to"] == uid
    if body is not None:
        assert body["assigned_to"] == _person(db, uid)
        assert PERSON_KEYS <= set(body["assigned_to"])


# ---- assign --------------------------------------------------------------------------------------

def test_assign_to_self_sets_assignee_on_detail_and_audits(db):
    _seed(db, "event", assigned_to=None)
    res = _assign(admin_id=ADM)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "open"
    _assert_assigned(db, ADM, body=body)
    logs = _report_logs(db)
    assert len(logs) == 1 and logs[0]["type"] == "report_assigned"
    assert logs[0]["created_by_id"] == ADM
    assert f"assigned_to:{ADM}" in logs[0]["values"]
    assert body == _detail(1)


def test_assign_to_another_admin(db):
    _seed(db, "event", assigned_to=None)
    res = _assign(admin_id=ADM2)
    assert res.status_code == 200, res.text
    _assert_assigned(db, ADM2, body=res.json())
    assert res.json()["assigned_to"]["username"] == "boss2"


def test_assign_is_idempotent_when_already_this_admin(db):
    _seed(db, "event", assigned_to=ADM)
    before = _snapshot(db)
    res = _assign(admin_id=ADM)
    assert res.status_code == 200, res.text
    _assert_assigned(db, ADM, body=res.json())
    assert _report_logs(db) == before["logs"]   # no second audit


def test_assign_rejects_when_already_assigned_to_someone_else(db):
    _seed(db, "event", assigned_to=ADM)
    before = _snapshot(db)
    res = _assign(admin_id=ADM2)
    assert res.status_code == 409, res.text
    assert _code(res) == "report_assigned"
    _assert_untouched(db, before)


def test_assign_trailing_slash_works(db):
    _seed(db, "event", assigned_to=None)
    res = client.post("/api/admin/reports/1/assign/", json={"admin_id": ADM}, follow_redirects=False)
    assert res.status_code == 200, res.text
    _assert_assigned(db, ADM, body=res.json())


def test_assign_closed_report_is_409(db):
    _seed(db, "event", status="dismissed", outcome="dismissed", closed_by=ADM,
          closed_at="2026-10-09T00:00:00+00:00", assigned_to=None)
    before = _snapshot(db)
    res = _assign(admin_id=ADM)
    assert res.status_code == 409 and _code(res) == "report_closed"
    _assert_untouched(db, before)


def test_assign_missing_report_is_404(db):
    res = _assign(rid=999, admin_id=ADM)
    assert res.status_code == 404 and _code(res) == "report_not_found"


def test_assign_regular_user_is_400(db):
    _seed(db, "event", assigned_to=None)
    before = _snapshot(db)
    res = _assign(admin_id=TOM)
    assert res.status_code == 400, res.text
    assert _code(res) == "not_an_administrator"
    _assert_untouched(db, before)


def test_assign_unknown_admin_is_404(db):
    _seed(db, "event", assigned_to=None)
    before = _snapshot(db)
    res = _assign(admin_id=MISSING)
    assert res.status_code == 404 and _code(res) == "admin_not_found"
    _assert_untouched(db, before)


def test_assign_missing_admin_id_is_422(db):
    _seed(db, "event", assigned_to=None)
    res = client.post("/api/admin/reports/1/assign", json={})
    assert res.status_code == 422


def test_assign_race_loses_to_the_other_admin(db, monkeypatch):
    """The conditional UPDATE sees assigned_to already set: 409, the other claim stands."""
    _seed(db, "event", assigned_to=None)
    original = _fake_supabase.FakeQuery.execute
    fired = []

    def execute(self):
        if (self.name == "reports" and self.action == "update"
                and (self.payload or {}).get("assigned_to") and not fired):
            fired.append(True)
            row = next(r for r in self.db.tables["reports"] if r["id"] == 1)
            row["assigned_to"] = ADM2
        return original(self)

    monkeypatch.setattr(_fake_supabase.FakeQuery, "execute", execute)
    res = _assign(admin_id=ADM)
    assert fired and res.status_code == 409 and _code(res) == "report_assigned"
    assert _row(db)["assigned_to"] == ADM2 and _row(db)["status"] == "open"


# ---- unassign ------------------------------------------------------------------------------------

def test_unassign_clears_assignee(db):
    _seed(db, "event", assigned_to=ADM)
    res = _unassign()
    assert res.status_code == 200, res.text
    assert res.json()["assigned_to"] is None
    assert _row(db)["assigned_to"] is None
    logs = _report_logs(db)
    assert len(logs) == 1 and logs[0]["type"] == "report_unassigned"
    assert f"was_assigned_to:{ADM}" in logs[0]["values"]


def test_unassign_by_another_admin(db):
    _seed(db, "event", assigned_to=ADM)
    _as(ADM2)
    res = _unassign()
    assert res.status_code == 200, res.text
    assert _row(db)["assigned_to"] is None
    assert _report_logs(db)[0]["created_by_id"] == ADM2


def test_unassign_already_null_is_idempotent(db):
    _seed(db, "event", assigned_to=None)
    before = _snapshot(db)
    res = _unassign()
    assert res.status_code == 200, res.text
    assert res.json()["assigned_to"] is None
    assert _report_logs(db) == before["logs"]


def test_unassign_closed_report_is_409(db):
    _seed(db, "event", status="dismissed", outcome="dismissed", closed_by=ADM,
          closed_at="2026-10-09T00:00:00+00:00", assigned_to=ADM)
    before = _snapshot(db)
    res = _unassign()
    assert res.status_code == 409 and _code(res) == "report_closed"
    _assert_untouched(db, before)


def test_unassign_trailing_slash_works(db):
    _seed(db, "event", assigned_to=ADM)
    res = client.post("/api/admin/reports/1/unassign/", follow_redirects=False)
    assert res.status_code == 200, res.text
    assert _row(db)["assigned_to"] is None


# ---- actions require the assignee ----------------------------------------------------------------

@pytest.mark.parametrize("call", [
    _dismiss,
    lambda: _act(action="warn"),
    lambda: _act(action="suspend"),
    lambda: _act(action="remove_content"),
], ids=["dismiss", "warn", "suspend", "remove"])
def test_unassigned_report_cannot_be_acted_on(db, call):
    _seed(db, "event", assigned_to=None)
    before = _snapshot(db)
    res = call()
    assert res.status_code == 403, res.text
    assert _code(res) == "report_unassigned"
    _assert_untouched(db, before)
    _assert_open_unchanged(db)


@pytest.mark.parametrize("call", [
    _dismiss,
    lambda: _act(action="warn"),
    lambda: _act(action="suspend"),
    lambda: _act(action="remove_content"),
], ids=["dismiss", "warn", "suspend", "remove"])
def test_other_admin_cannot_act_on_assigned_report(db, call):
    _seed(db, "event", assigned_to=ADM2)
    before = _snapshot(db)
    res = call()
    assert res.status_code == 403, res.text
    assert _code(res) == "report_assigned_to_other"
    _assert_untouched(db, before)
    assert _row(db)["assigned_to"] == ADM2


def test_assignee_can_dismiss(db):
    _seed(db, "event", assigned_to=ADM)
    res = _dismiss()
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "dismissed"
    assert res.json()["assigned_to"]["id"] == ADM


def test_assignee_can_warn(db):
    _seed(db, "user", assigned_to=ADM)
    res = _act(action="warn")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "resolved" and res.json()["outcome"] == "warned"


def test_assign_then_other_admin_still_blocked(db):
    _seed(db, "event", assigned_to=None)
    assert _assign(admin_id=ADM).status_code == 200
    _as(ADM2)
    res = _dismiss()
    assert res.status_code == 403 and _code(res) == "report_assigned_to_other"
    assert _row(db)["status"] == "open" and _row(db)["assigned_to"] == ADM


def test_reassign_after_unassign(db):
    _seed(db, "event", assigned_to=ADM)
    assert _unassign().status_code == 200
    res = _assign(admin_id=ADM2)
    assert res.status_code == 200, res.text
    _assert_assigned(db, ADM2, body=res.json())


# ---- admin-only chain ----------------------------------------------------------------------------

def _jwt(payload):
    import base64
    import json
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{enc({'alg': 'HS256'})}.{enc(payload)}.sig"


def _real_chain(mock_sb, role, aal):
    app.dependency_overrides.clear()
    mock_sb.auth.get_user.return_value = MagicMock(user=SimpleNamespace(id=ADM))
    chain = MagicMock()
    chain.select.return_value = chain.eq.return_value = chain.single.return_value = chain
    chain.execute.return_value = MagicMock(data={"role": role})
    mock_sb.table.return_value = chain
    return {"Authorization": f"Bearer {_jwt({'sub': ADM, 'aal': aal})}"}


ASSIGN_ENDPOINTS = [
    ("/api/admin/reports/1/assign", {"admin_id": ADM}),
    ("/api/admin/reports/1/assign/", {"admin_id": ADM}),
    ("/api/admin/reports/1/unassign", None),
    ("/api/admin/reports/1/unassign/", None),
]
ASSIGN_IDS = ["assign", "assign_slash", "unassign", "unassign_slash"]


def _post(url, body, headers=None):
    return client.post(url, json=body, headers=headers or {}, follow_redirects=False)


@pytest.mark.parametrize("url,body", ASSIGN_ENDPOINTS, ids=ASSIGN_IDS)
@patch("app.core.dependencies.supabase")
def test_assign_real_chain_user_role_gets_403(mock_sb, db, url, body):
    _seed(db, "event", assigned_to=None if "/unassign" not in url else ADM)
    headers = _real_chain(mock_sb, "user", "aal2")
    before = _snapshot(db)
    res = _post(url, body, headers)
    assert res.status_code == 403, f"{url}: {res.status_code} {res.text}"
    _assert_untouched(db, before)


@pytest.mark.parametrize("url,body", ASSIGN_ENDPOINTS, ids=ASSIGN_IDS)
@patch("app.core.dependencies.supabase")
def test_assign_real_chain_administrator_with_mfa_succeeds(mock_sb, db, url, body):
    assigning = "unassign" not in url
    _seed(db, "event", assigned_to=None if assigning else ADM)
    headers = _real_chain(mock_sb, "administrator", "aal2")
    res = _post(url, body, headers)
    assert res.status_code == 200, f"{url}: {res.status_code} {res.text}"
    assert res.json()["status"] == "open"
    if assigning:
        assert res.json()["assigned_to"]["id"] == ADM
    else:
        assert res.json()["assigned_to"] is None


def test_openapi_exposes_assign_and_unassign():
    spec = client.get("/openapi.json").json()
    assert "/api/admin/reports/{report_id}/assign" in spec["paths"]
    assert "/api/admin/reports/{report_id}/unassign" in spec["paths"]
