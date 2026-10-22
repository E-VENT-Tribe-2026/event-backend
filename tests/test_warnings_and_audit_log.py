"""Ticket #191: warnings and the audit log, through direct API requests.

Routes and services run for real against the in-memory Supabase fake (tests/_fake_supabase.py).
Cast: ADM is an administrator, U and V are users. U and V are friends, U blocked W, X blocked U.
"""
import base64
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_current_onboarded_user, require_admin, require_regular_user
from app.main import app
from tests._fake_supabase import FakeSupabase

ADM = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
ADM2 = "abababab-abab-4bab-8bab-abababababab"
U = "11111111-1111-4111-8111-111111111111"
V = "22222222-2222-4222-8222-222222222222"
W = "33333333-3333-4333-8333-333333333333"
X = "44444444-4444-4444-8444-444444444444"

MODULES = ["admin_service", "warning_service", "audit_service", "notification_service", "profile_service"]
client = TestClient(app)
current = {"id": U}


def _profile(uid, username, role="user", visibility="public", suspended_at=None):
    return {"id": uid, "username": username, "full_name": username.title(), "role": role,
            "visibility": visibility, "avatar_url": f"https://img/{username}.png", "avatar_kind": "photo",
            "icon_id": None, "created_at": "2026-01-01T00:00:00+00:00", "suspended_at": suspended_at}


@pytest.fixture
def db():
    fake = FakeSupabase()
    fake.tables["profiles"] = [
        _profile(ADM, "boss", role="administrator"),
        _profile(ADM2, "boss2", role="administrator"),
        _profile(U, "ulla", visibility="friends_only"),
        _profile(V, "vera"),
        _profile(W, "wim", suspended_at="2026-10-01T00:00:00+00:00"),
        _profile(X, "xena"),
    ]
    fake.tables["friendships"] = [{"id": 1, "user_id": U, "friend_id": V}]
    fake.tables["user_blocks"] = [{"blocker_id": U, "blocked_id": W}, {"blocker_id": X, "blocked_id": U}]
    fake.tables["events"], fake.tables["event_participants"] = [], []

    patches = [patch(f"app.services.{m}.supabase", fake) for m in MODULES]
    for p in patches:
        p.start()
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id=current["id"])
    app.dependency_overrides[require_regular_user] = lambda: SimpleNamespace(id=current["id"])
    yield fake
    for p in patches:
        p.stop()
    app.dependency_overrides.clear()


def as_(uid):
    current["id"] = uid


def give(user_id, reason="Spam in event chat", admin=ADM, **body):
    as_(admin)
    return client.post(f"/api/admin/users/{user_id}/warnings", json={"reason": reason, **body})


# ---- giving a warning -------------------------------------------------------

def test_give_warning_creates_warning_notification_and_audit_entry(db):
    res = give(U, about_type="event", about_id="e1")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["reason"] == "Spam in event chat"
    assert body["about"] == {"type": "event", "id": "e1"}
    assert body["given_by"]["username"] == "boss"

    note = db.tables["notifications"][0]
    assert note["user_id"] == U and note["type"] == "warning" and note["message"] == "Spam in event chat"
    assert note["warning_id"] == body["id"]

    log = db.tables["logs"][0]
    assert log["type"] == "warning_given" and log["created_by_id"] == ADM and log["entity_id"] == U


@pytest.mark.parametrize("reason", ["", "   "])
def test_warning_without_reason_is_refused(db, reason):
    assert give(U, reason=reason).status_code == 422
    assert not db.tables.get("warnings")


def test_warning_an_administrator_is_refused(db):
    res = give(ADM2)
    assert res.status_code == 400
    assert not db.tables.get("warnings")


def test_warning_unknown_user_is_404(db):
    assert give("99999999-9999-4999-8999-999999999999").status_code == 404


# ---- notifications ----------------------------------------------------------

def test_notification_list_marks_warning_and_its_acknowledgement(db):
    wid = give(U).json()["id"]
    as_(U)
    app.dependency_overrides[get_current_onboarded_user] = lambda: SimpleNamespace(id=U)
    note = client.get("/api/notifications/all").json()["data"][0]
    assert note["is_warning"] is True and note["warning_acknowledged"] is False

    client.post(f"/api/warnings/{wid}/acknowledge")
    note = client.get("/api/notifications/all").json()["data"][0]
    assert note["warning_acknowledged"] is True and note["is_read"] is True


# ---- pending and acknowledging ---------------------------------------------

def test_pending_warnings_oldest_first_and_gone_after_acknowledging(db):
    first = give(U, reason="first").json()["id"]
    give(U, reason="second")
    as_(U)
    pending = client.get("/api/warnings/pending").json()["items"]
    assert [w["reason"] for w in pending] == ["first", "second"]

    assert client.post(f"/api/warnings/{first}/acknowledge").status_code == 200
    # "Another device" is just another request: the state is stored on the server.
    assert [w["reason"] for w in client.get("/api/warnings/pending").json()["items"]] == ["second"]
    # Acknowledging twice is fine.
    assert client.post(f"/api/warnings/{first}/acknowledge").status_code == 200


def test_user_cannot_acknowledge_someone_elses_warning(db):
    wid = give(U).json()["id"]
    as_(V)
    assert client.post(f"/api/warnings/{wid}/acknowledge").status_code == 404


def test_withdrawn_warning_is_not_pending(db):
    wid = give(U).json()["id"]
    as_(ADM)
    client.post(f"/api/admin/warnings/{wid}/withdraw")
    as_(U)
    assert client.get("/api/warnings/pending").json()["items"] == []


# ---- withdrawing and history -----------------------------------------------

def test_withdrawn_warning_stays_in_history_and_no_longer_counts(db):
    keep = give(U, reason="keep").json()["id"]
    gone = give(U, reason="mistake").json()["id"]

    as_(ADM2)
    res = client.post(f"/api/admin/warnings/{gone}/withdraw")
    assert res.status_code == 200
    assert res.json()["withdrawn_by"]["username"] == "boss2"
    assert client.post(f"/api/admin/warnings/{gone}/withdraw").status_code == 409

    history = client.get(f"/api/admin/users/{U}/warnings").json()["items"]
    assert [h["reason"] for h in history] == ["mistake", "keep"]          # newest first
    assert history[0]["is_withdrawn"] and history[0]["withdrawn_at"]
    assert history[0]["given_by"]["username"] == "boss"
    assert not history[1]["is_withdrawn"] and history[1]["id"] == keep

    details = client.get(f"/api/admin/users/{U}").json()
    assert details["warning_count"] == 1
    assert db.tables["logs"][-1]["type"] == "warning_withdrawn"


def test_withdrawing_unknown_warning_is_404(db):
    as_(ADM)
    assert client.post("/api/admin/warnings/12345/withdraw").status_code == 404


# ---- user list, counters, details -------------------------------------------

def test_user_list_counts_status_and_admin_shows_role_only(db):
    give(U)
    give(U)
    as_(ADM)
    items = {i["id"]: i for i in client.get("/api/admin/users?limit=100").json()["items"]}
    assert items[U]["warning_count"] == 2 and items[U]["status"] == "active"
    assert items[W]["warning_count"] == 0 and items[W]["status"] == "suspended"
    assert items[ADM]["role"] == "administrator"
    assert items[ADM]["warning_count"] is None and items[ADM]["status"] is None
    # Fields the existing panel relies on are still there.
    for key in ("id", "username", "full_name", "display_name", "avatar_url", "avatar_kind",
                "icon_id", "role", "is_admin", "created_at"):
        assert key in items[U]


def test_counters_and_filters_work_with_search(db):
    give(U)
    give(V)
    as_(ADM)
    assert client.get("/api/admin/users/counters").json() == \
        {"administrators": 2, "suspended": 1, "with_warnings": 2}

    def ids(q):
        return {i["id"] for i in client.get(f"/api/admin/users?{q}").json()["items"]}

    assert ids("filter=administrators") == {ADM, ADM2}
    assert ids("filter=suspended") == {W}
    assert ids("filter=with_warnings") == {U, V}
    assert ids("filter=with_warnings&search=ver") == {V}
    assert ids("filter=administrators&search=ulla") == set()
    assert client.get("/api/admin/users?filter=nonsense").status_code == 422


def test_user_details_show_relations_even_when_friends_only(db):
    give(U)
    as_(ADM)
    d = client.get(f"/api/admin/users/{U}").json()
    assert d["profile_visibility"] == "friends_only"
    assert d["status"] == "active" and d["warning_count"] == 1
    assert [f["username"] for f in d["friends"]] == ["vera"]
    assert [b["username"] for b in d["blocked_users"]] == ["wim"]
    assert [b["username"] for b in d["blocked_by"]] == ["xena"]
    assert d["friends"][0]["avatar_url"] and d["friends"][0]["full_name"] == "Vera"


# ---- audit log ---------------------------------------------------------------

def test_audit_log_newest_first_in_pages(db):
    for i in range(3):
        give(U, reason=f"r{i}")
    as_(ADM)
    page1 = client.get("/api/admin/audit-log?limit=2").json()
    assert page1["has_more"] is True
    assert [i["details"] for i in page1["items"]][0][1] == "reason:r2"
    entry = page1["items"][0]
    assert entry["action"] == "warning_given"
    assert entry["administrator"]["username"] == "boss"
    assert entry["target"]["type"] == "user" and entry["target"]["user"]["username"] == "ulla"

    page2 = client.get(f"/api/admin/audit-log?limit=2&before={page1['next_before']}").json()
    assert page2["has_more"] is False and len(page2["items"]) == 1
    assert page2["items"][0]["details"][1] == "reason:r0"


# ---- only administrators ----------------------------------------------------

def _jwt(payload):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{enc({'alg': 'HS256'})}.{enc(payload)}.sig"


ADMIN_ENDPOINTS_191 = [
    ("POST", f"/api/admin/users/{U}/warnings"),
    ("GET", f"/api/admin/users/{U}/warnings"),
    ("POST", "/api/admin/warnings/1/withdraw"),
    ("GET", "/api/admin/users"),
    ("GET", "/api/admin/users/counters"),
    ("GET", f"/api/admin/users/{U}"),
    ("GET", "/api/admin/audit-log"),
]


@pytest.mark.parametrize("method,url", ADMIN_ENDPOINTS_191)
@patch("app.core.dependencies.supabase")
def test_user_account_is_refused_on_every_admin_endpoint(mock_sb, method, url):
    app.dependency_overrides.clear()
    mock_sb.auth.get_user.return_value = MagicMock(user=SimpleNamespace(id=U))
    chain = MagicMock()
    chain.select.return_value = chain.eq.return_value = chain.single.return_value = chain
    chain.execute.return_value = MagicMock(data={"role": "user"})
    mock_sb.table.return_value = chain

    headers = {"Authorization": f"Bearer {_jwt({'sub': U, 'aal': 'aal2'})}"}
    res = client.request(method, url, headers=headers, json={"reason": "x"})
    assert res.status_code == 403, f"{method} {url} must refuse a user account"