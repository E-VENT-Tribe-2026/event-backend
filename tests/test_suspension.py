"""Ticket #192: suspending accounts and the effects of suspension, through direct API requests.

Routes and services run for real against the in-memory Supabase fake (tests/_fake_supabase.py).
Cast: ADM is an administrator. S is the user who gets suspended, P takes part in S's events,
V is a viewer. S and V are friends of nobody, so S would normally be suggested to V.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from gotrue.errors import AuthApiError

from app.core.dependencies import require_admin
from app.main import app
from tests._fake_supabase import FakeSupabase

ADM = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
S = "55555555-5555-4555-8555-555555555555"
P = "66666666-6666-4666-8666-666666666666"
V = "77777777-7777-4777-8777-777777777777"

FUTURE = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
PAST = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
E_UP, E_PAST = "00000000-0000-4000-8000-0000000000e1", "00000000-0000-4000-8000-0000000000e2"
E_OTHER_UP, E_OTHER_PAST = "00000000-0000-4000-8000-0000000000e3", "00000000-0000-4000-8000-0000000000e4"

MODULES = ["admin_service", "warning_service", "audit_service", "notification_service", "profile_service",
           "suspension_service", "friendship_service", "block_visibility", "chat_service",
           "admin_report_history_service"]
client = TestClient(app)
current = {"id": ADM}


def _profile(uid, username, role="user"):
    return {"id": uid, "username": username, "full_name": username.title(), "role": role,
            "visibility": "public", "avatar_url": None, "avatar_kind": "icon", "icon_id": None,
            "created_at": "2026-01-01T00:00:00+00:00", "suspended_at": None, "suspension_reason": None,
            "interest_embedding": None}


def _event(eid, organizer, start, title):
    return {"id": eid, "title": title, "created_by": organizer, "status": "active",
            "start_datetime": start, "end_datetime": start}


@pytest.fixture
def db():
    fake = FakeSupabase()
    fake.tables["profiles"] = [_profile(ADM, "boss", "administrator"), _profile(S, "sam"),
                               _profile(P, "pia"), _profile(V, "vic")]
    fake.tables["events"] = [
        _event(E_UP, S, FUTURE, "Sam upcoming"), _event(E_PAST, S, PAST, "Sam past"),
        _event(E_OTHER_UP, P, FUTURE, "Pia upcoming"), _event(E_OTHER_PAST, P, PAST, "Pia past"),
    ]
    fake.tables["event_participants"] = [
        {"id": 1, "event_id": E_UP, "user_id": P},
        {"id": 2, "event_id": E_PAST, "user_id": P},
        {"id": 3, "event_id": E_OTHER_UP, "user_id": S},
        {"id": 4, "event_id": E_OTHER_PAST, "user_id": S},
    ]
    # Signed-in users: the token is the user id; S signed in with Google.
    providers = {S: "google"}
    fake.auth = SimpleNamespace(get_user=lambda token: SimpleNamespace(
        user=SimpleNamespace(id=token, email=f"{token}@x.io",
                             app_metadata={"provider": providers.get(token, "email")})))

    patches = [patch(f"app.services.{m}.supabase", fake) for m in MODULES]
    patches += [
        patch("app.core.dependencies.supabase", fake),
        patch("app.db.supabase_client.supabase", fake),
        patch("app.services.event_service._email_participants", lambda *a, **k: None),
        patch("app.services.reminder_service._get_user_email", lambda uid: None),   # no real email lookups
    ]
    for p in patches:
        p.start()
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id=current["id"])
    yield fake
    for p in patches:
        p.stop()
    app.dependency_overrides.clear()


def suspend(uid=S, reason="Harassment in chats"):
    return client.post(f"/api/admin/users/{uid}/suspend", json={"reason": reason})


def lift(uid=S, reason="Appeal accepted"):
    return client.post(f"/api/admin/users/{uid}/lift-suspension", json={"reason": reason})


def as_user(uid):
    return {"Authorization": f"Bearer {uid}"}


def _row(db, table, **match):
    return next(r for r in db.tables[table] if all(r.get(k) == v for k, v in match.items()))


# ---- suspending and lifting -------------------------------------------------

def test_suspend_needs_reason_refuses_admins_unknown_and_twice(db):
    assert client.post(f"/api/admin/users/{S}/suspend", json={"reason": "  "}).status_code == 422
    assert suspend(ADM).status_code == 400
    assert suspend("99999999-9999-4999-8999-999999999999").status_code == 404
    assert suspend().status_code == 200
    assert suspend().status_code == 409
    assert client.post(f"/api/admin/users/{S}/lift-suspension", json={"reason": ""}).status_code == 422


def test_suspend_and_lift_are_audited_and_shown_in_the_panel(db):
    res = suspend()
    assert res.json()["status"] == "suspended" and res.json()["suspended_since"]

    details = client.get(f"/api/admin/users/{S}").json()
    assert details["status"] == "suspended"
    assert details["suspended_since"] == res.json()["suspended_since"]
    assert details["suspension_reason"] == "Harassment in chats"
    assert client.get("/api/admin/users/counters").json()["suspended"] == 1

    assert lift().status_code == 200
    assert lift().status_code == 409          # not suspended any more
    details = client.get(f"/api/admin/users/{S}").json()
    assert details["status"] == "active" and details["suspended_since"] is None

    actions = [r["type"] for r in db.tables["logs"]]
    assert actions == ["account_suspended", "suspension_lifted"]
    assert "reason:Appeal accepted" in db.tables["logs"][1]["values"]


def test_warnings_never_suspend(db):
    for i in range(5):
        client.post(f"/api/admin/users/{S}/warnings", json={"reason": f"r{i}"})
    assert client.get(f"/api/admin/users/{S}").json()["status"] == "active"


# ---- effects on events ------------------------------------------------------

def test_suspension_cancels_upcoming_events_and_leaves_joined_ones(db):
    res = suspend().json()
    assert res["cancelled_events_count"] == 1 and res["joined_events_removed_count"] == 1

    up = _row(db, "events", id=E_UP)
    assert up["status"] == "cancelled" and up["cancellation_reason"] == "Organizer's account was suspended"
    assert _row(db, "events", id=E_PAST)["status"] == "active"           # past event untouched

    notes = [n for n in db.tables["notifications"] if n["user_id"] == P]
    assert notes and notes[0]["type"] == "event_cancelled" and notes[0]["event_id"] == E_UP

    joined = {r["event_id"] for r in db.tables["event_participants"] if r["user_id"] == S}
    assert joined == {E_OTHER_PAST}                                      # left upcoming, kept past
    assert any(r["event_id"] == E_PAST and r["user_id"] == P for r in db.tables["event_participants"])

    from app.services.chat_service import send_message
    with pytest.raises(HTTPException) as err:                            # chat is read-only
        send_message(P, E_UP, "hello?")
    assert "read-only" in str(err.value.detail)


def test_lifting_restores_nothing_that_was_cancelled(db):
    suspend()
    lift()
    assert _row(db, "events", id=E_UP)["status"] == "cancelled"
    assert not any(r["event_id"] == E_OTHER_UP and r["user_id"] == S for r in db.tables["event_participants"])


def test_lifting_sends_an_email(db):
    suspend()
    with patch("app.services.reminder_service._get_user_email", return_value="sam@x.io"), \
         patch("app.services.email_service.send_email") as send:
        assert lift().status_code == 200
    assert send.call_args[0][0] == "sam@x.io"


def test_lifting_succeeds_even_if_the_email_fails(db):
    suspend()
    with patch("app.services.reminder_service._get_user_email", return_value="sam@x.io"), \
         patch("app.services.email_service.send_email", side_effect=RuntimeError("email service down")):
        res = lift()
    assert res.status_code == 200 and res.json()["status"] == "active"


# ---- every request of a suspended account is refused -------------------------

def test_every_request_with_an_existing_sign_in_is_refused_including_google(db):
    assert client.get("/api/warnings/pending", headers=as_user(S)).status_code == 200
    suspend()
    for method, url in [("GET", "/api/warnings/pending"), ("GET", "/api/auth/me"),
                        ("GET", f"/api/events/{E_OTHER_UP}"),        # public endpoint, optional sign-in
                        ("GET", "/api/notifications/all")]:
        res = client.request(method, url, headers=as_user(S))
        assert res.status_code == 403, f"{method} {url}"
        assert res.json()["detail"]["code"] == "account_suspended"
        assert res.json()["detail"]["reason"] == "Harassment in chats"
    # Other users are not affected.
    assert client.get("/api/warnings/pending", headers=as_user(V)).status_code == 200

    lift()
    assert client.get("/api/warnings/pending", headers=as_user(S)).status_code == 200


def test_sign_in_is_refused_with_reason_only_for_correct_credentials(db):
    suspend()
    session_ok = SimpleNamespace(session=SimpleNamespace(access_token="tok"), user=SimpleNamespace(id=S))

    with patch("app.services.auth_service.supabase") as sb:
        sb.auth.sign_in_with_password.return_value = session_ok
        sb.table.side_effect = db.table
        res = client.post("/api/auth/login", json={"email": "sam@x.io", "password": "Correct-pass1"})
        assert res.status_code == 403
        assert res.json()["detail"] == {"code": "account_suspended", "message": "Your account is suspended.",
                                        "reason": "Harassment in chats"}
        assert "access_token" not in res.text

        sb.auth.sign_in_with_password.side_effect = AuthApiError("Invalid login credentials", 400)
        res = client.post("/api/auth/login", json={"email": "sam@x.io", "password": "Wrong-pass1"})
        assert res.status_code == 401
        assert "suspend" not in res.text.lower()


# ---- hidden from search and suggestions, profile unavailable -----------------

def test_suspended_account_is_hidden_and_its_profile_unavailable(db):
    from app.services.profile_service import search_profiles
    from app.services.friendship_service import get_friend_suggestions
    from app.services.public_profile_service import build_public_profile

    def suggested():
        return {s["user"]["id"] for s in get_friend_suggestions(V)["data"]}

    assert [r["id"] for r in search_profiles("sam", 1, 10, V)["data"]] == [S]
    assert S in suggested()

    suspend()
    assert search_profiles("sam", 1, 10, V)["data"] == []
    assert S not in suggested() and P in suggested()
    with pytest.raises(HTTPException) as err:
        build_public_profile(S, V)
    assert err.value.status_code == 404 and err.value.detail["code"] == "profile_unavailable"

    lift()
    assert [r["id"] for r in search_profiles("sam", 1, 10, V)["data"]] == [S]


def test_past_events_keep_the_suspended_organizer(db):
    suspend()
    past = _row(db, "events", id=E_PAST)
    assert past["created_by"] == S and past["status"] == "active"


# ---- only administrators ----------------------------------------------------

@pytest.mark.parametrize("url", [f"/api/admin/users/{S}/suspend", f"/api/admin/users/{S}/lift-suspension"])
def test_user_account_is_refused(db, url):
    app.dependency_overrides.clear()
    import base64, json
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    token = f"{enc({'alg': 'HS256'})}.{enc({'sub': V, 'aal': 'aal2'})}.sig"
    db.auth = SimpleNamespace(get_user=lambda t: SimpleNamespace(user=SimpleNamespace(id=V)))
    res = client.post(url, headers={"Authorization": f"Bearer {token}"}, json={"reason": "x"})
    assert res.status_code == 403
    assert _row(db, "profiles", id=S)["suspended_at"] is None