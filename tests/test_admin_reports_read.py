"""Ticket #235 phase 2: admin Reports tab, read endpoints (test first).

  GET /api/admin/reports/open, GET /api/admin/reports, GET /api/admin/reports/{report_id}

Driven through HTTP against the real app and the in-memory Supabase fake (tests/_fake_supabase.py).
Every `supabase` name in app.services.* (except the two patched by conftest) and in the admin routes
module is swapped for the same fake, so the implementation may query however it likes with the
operations the fake supports (select/eq/in_/is_/order/range/limit/single/count).
"""
import base64
import importlib
import json
import pkgutil
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import app.services as services_pkg
from app.core.dependencies import require_admin
from app.main import app
from tests._fake_supabase import FakeSupabase

ADM = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
ADM2 = "abababab-abab-4bab-8bab-abababababab"
MIA = "11111111-1111-4111-8111-111111111111"   # reporter
TOM = "22222222-2222-4222-8222-222222222222"   # reported user / message author / organizer
ANA = "33333333-3333-4333-8333-333333333333"   # second reporter
EV1 = "550e8400-e29b-41d4-a716-446655440000"
EV2 = "9b2f3c1e-6a47-4c0e-8d55-0f1a2b3c4d5e"

client = TestClient(app)
SKIP_MODULES = {"block_visibility", "removed_content"}  # conftest patches these itself


def _profile(uid, username, role="user"):
    return {"id": uid, "username": username, "full_name": username.title(), "role": role,
            "avatar_url": f"https://img/{username}.png", "avatar_kind": "photo", "icon_id": None,
            "visibility": "public", "created_at": "2026-01-01T00:00:00+00:00", "suspended_at": None}


def _event(eid, title, created_by=TOM, removed_at=None):
    return {"id": eid, "title": title, "created_by": created_by, "banner_url": f"https://img/{title}.jpg",
            "status": "active", "start_datetime": "2027-01-01T00:00:00+00:00",
            "end_datetime": "2027-01-01T02:00:00+00:00", "removed_at": removed_at, "removed_by": None}


def _report(rid, created_at, **kw):
    row = {"id": rid, "reporter_id": MIA, "target_type": "event", "event_id": EV1, "reported_user_id": None,
           "message_id": None, "reason": "spam", "description": None, "origin": "event_details",
           "status": "open", "chat_context": None, "created_at": created_at,
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


@pytest.fixture
def db():
    fake = FakeSupabase()
    fake.tables["profiles"] = [_profile(ADM, "boss", "administrator"), _profile(ADM2, "boss2", "administrator"),
                               _profile(MIA, "mia"), _profile(TOM, "tom"), _profile(ANA, "ana")]
    fake.tables["events"] = [_event(EV1, "Board game night"), _event(EV2, "Sunset party")]
    fake.tables["event_chats"] = []
    fake.tables["reports"] = []
    fake.tables["event_participants"] = []
    fake.tables["user_blocks"] = []
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


def _chat(id_, event_id=EV1, sender=TOM, removed_at=None):
    return {"id": id_, "event_id": event_id, "sender_id": sender, "content": f"msg {id_}", "type": "chat",
            "removed_at": removed_at, "removed_by": None, "created_at": f"2026-10-28T18:00:{id_:02d}+00:00"}


CLOSED = {"status": "dismissed", "outcome": "dismissed", "closed_by": ADM, "closed_at": "2026-10-09T00:00:00+00:00"}


# ---- GET /api/admin/reports/open ---------------------------------------------

def test_open_list_newest_first_with_total_and_only_open(db):
    _put(db,
         _report(1, "2026-10-01T10:00:00+00:00"),
         _report(2, "2026-10-03T10:00:00+00:00", event_id=EV2),
         _report(3, "2026-10-02T10:00:00+00:00", **CLOSED),
         _report(4, "2026-10-03T10:00:00+00:00", event_id=EV2, reporter_id=ANA),
         _report(5, "2026-10-05T00:00:00+00:00", status="action_taken", outcome="warned",
                 closed_by=ADM, closed_at="2026-10-06T00:00:00+00:00"))
    res = client.get("/api/admin/reports/open")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 3
    assert _ids(body["items"]) == [4, 2, 1]  # created_at desc, id desc as tiebreak
    assert all(i["status"] == "open" for i in body["items"])


def test_open_list_is_not_paged(db):
    _put(db, *[_report(i, f"2026-10-01T10:{i:02d}:00+00:00") for i in range(1, 31)])
    res = client.get("/api/admin/reports/open")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 30 and len(body["items"]) == 30


def test_open_list_empty(db):
    res = client.get("/api/admin/reports/open")
    assert res.status_code == 200, res.text
    assert res.json() == {"total": 0, "items": []}


def test_open_path_is_not_taken_as_a_report_id(db):
    # /reports/open must reach the list, not the details route (which would 404 or 422 on "open").
    res = client.get("/api/admin/reports/open")
    assert res.status_code == 200 and "items" in res.json()


# ---- GET /api/admin/reports --------------------------------------------------

def _many(db, n):
    _put(db, *[_report(i, f"2026-10-01T10:{i:02d}:00+00:00", **(CLOSED if i % 2 == 0 else {}))
               for i in range(1, n + 1)])


def test_all_list_pages_total_and_order(db):
    _many(db, 45)
    res = client.get("/api/admin/reports?page=1&limit=20")
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["total"], body["page"], body["limit"], body["total_pages"]) == (45, 1, 20, 3)
    assert _ids(body["items"]) == list(range(45, 25, -1))
    assert {i["status"] for i in body["items"]} == {"open", "dismissed"}  # all statuses

    page2 = client.get("/api/admin/reports?page=2&limit=20").json()
    assert _ids(page2["items"]) == list(range(25, 5, -1)) and page2["page"] == 2
    page3 = client.get("/api/admin/reports?page=3&limit=20").json()
    assert _ids(page3["items"]) == [5, 4, 3, 2, 1]


def test_all_list_page_past_the_end_is_empty(db):
    _many(db, 5)
    res = client.get("/api/admin/reports?page=9&limit=20")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["items"] == [] and body["total"] == 5 and body["total_pages"] == 1


def test_all_list_default_limit_is_20(db):
    _many(db, 25)
    res = client.get("/api/admin/reports")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["limit"] == 20 and body["page"] == 1 and len(body["items"]) == 20
    assert body["total_pages"] == 2


def test_all_list_total_pages_rounds_up(db):
    _many(db, 11)
    res = client.get("/api/admin/reports?limit=5")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 11 and body["total_pages"] == 3 and len(body["items"]) == 5


def test_all_list_limit_100_allowed(db):
    _many(db, 3)
    res = client.get("/api/admin/reports?limit=100")
    assert res.status_code == 200, res.text
    assert res.json()["limit"] == 100


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "limit=-1", "page=0", "limit=abc"])
def test_all_list_out_of_range_is_422(db, query):
    assert client.get(f"/api/admin/reports?{query}").status_code == 422


# ---- item shapes (both lists) ------------------------------------------------

PERSON_KEYS = {"id", "username", "full_name", "display_name", "avatar_kind", "icon_id", "avatar_url"}


def _both_lists():
    out = []
    for url in ("/api/admin/reports/open", "/api/admin/reports"):
        res = client.get(url)
        assert res.status_code == 200, f"{url}: {res.status_code} {res.text}"
        out.append(res.json()["items"])
    return out


def test_event_report_item(db):
    _put(db, _report(1, "2026-10-01T10:00:00+00:00"))
    for items in _both_lists():
        assert len(items) == 1
        item = items[0]
        assert {"id", "status", "reason", "created_at", "target_type", "origin", "reporter", "reported"} <= set(item)
        assert (item["id"], item["status"], item["reason"], item["target_type"], item["origin"]) == \
               (1, "open", "spam", "event", "event_details")
        assert PERSON_KEYS <= set(item["reporter"])
        assert item["reporter"]["id"] == MIA and item["reporter"]["username"] == "mia"
        rep = item["reported"]
        assert rep["type"] == "event" and rep["user"] is None and rep["message"] is None
        assert rep["event"]["id"] == EV1 and rep["event"]["title"] == "Board game night"
        assert rep["event"]["banner_url"] == "https://img/Board game night.jpg"
        assert {"id", "title", "banner", "banner_url"} <= set(rep["event"])


def test_user_report_item(db):
    _put(db, _report(1, "2026-10-01T10:00:00+00:00", target_type="user", event_id=None, reported_user_id=TOM,
                     origin="profile", reason="harassment_or_hate"))
    for items in _both_lists():
        rep = items[0]["reported"]
        assert items[0]["target_type"] == "user" and items[0]["origin"] == "profile"
        assert rep["type"] == "user" and rep["event"] is None and rep["message"] is None
        assert PERSON_KEYS <= set(rep["user"])
        assert rep["user"]["id"] == TOM and rep["user"]["username"] == "tom"


def test_message_report_item(db):
    db.tables["event_chats"].append(_chat(42))
    _put(db, _report(1, "2026-10-01T10:00:00+00:00", target_type="message", event_id=EV1, reported_user_id=TOM,
                     message_id=42, origin="event_chat", reason="harassment_or_hate"))
    for items in _both_lists():
        item = items[0]
        rep = item["reported"]
        assert item["target_type"] == "message" and item["origin"] == "event_chat"
        assert rep["type"] == "message"
        assert rep["message"] == {"id": 42, "event_id": EV1}
        assert rep["user"]["id"] == TOM and rep["user"]["username"] == "tom"
        assert rep["event"] is None  # null in the list


def test_deleted_reporter_gives_null(db):
    _put(db, _report(1, "2026-10-01T10:00:00+00:00", reporter_id=None))
    for items in _both_lists():
        assert items[0]["reporter"] is None
        assert items[0]["reported"]["event"]["id"] == EV1


def test_deleted_event_gives_null_event(db):
    _put(db, _report(1, "2026-10-01T10:00:00+00:00", event_id=None))
    for items in _both_lists():
        rep = items[0]["reported"]
        assert rep["type"] == "event" and rep["event"] is None
        assert items[0]["reporter"]["id"] == MIA


def test_deleted_reported_user_gives_null_user(db):
    _put(db, _report(1, "2026-10-01T10:00:00+00:00", target_type="user", event_id=None, reported_user_id=None,
                     origin="profile"))
    for items in _both_lists():
        assert items[0]["reported"]["type"] == "user" and items[0]["reported"]["user"] is None


def test_deleted_message_author_gives_null_user(db):
    _put(db, _report(1, "2026-10-01T10:00:00+00:00", target_type="message", reported_user_id=None,
                     message_id=42, origin="event_chat"))
    for items in _both_lists():
        rep = items[0]["reported"]
        assert rep["message"] == {"id": 42, "event_id": EV1} and rep["user"] is None


# ---- GET /api/admin/reports/{report_id} --------------------------------------

DETAIL_KEYS = {"id", "status", "reason", "description", "created_at", "origin", "reporter", "target_type",
               "reported", "event", "chat_context", "outcome", "closed_by", "closed_at", "content_removed",
               "reported_user_is_administrator"}


def _detail(rid):
    res = client.get(f"/api/admin/reports/{rid}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert DETAIL_KEYS <= set(body)
    return body


def test_details_event_report_from_event_details(db):
    _put(db, _report(1, "2026-10-01T10:00:00+00:00", reason="misleading_event", description="Not real."))
    body = _detail(1)
    assert body["description"] == "Not real." and body["origin"] == "event_details"
    assert body["reporter"]["username"] == "mia"
    assert body["reported"]["type"] == "event" and body["reported"]["event"]["id"] == EV1
    assert body["event"] is None and body["chat_context"] is None
    assert body["outcome"] is None and body["closed_by"] is None and body["closed_at"] is None
    assert body["content_removed"] is False and body["reported_user_is_administrator"] is False


def test_details_event_report_from_event_chat(db):
    ctx = [{"id": 41, "type": "chat", "sender_id": MIA, "sender_name": "Mia", "content": "Hi",
            "created_at": "2026-10-28T18:00:40+00:00", "reported": False}]
    _put(db, _report(1, "2026-10-01T10:00:00+00:00", origin="event_chat", chat_context=ctx))
    body = _detail(1)
    assert body["origin"] == "event_chat"
    assert body["event"]["id"] == EV1 and body["event"]["title"] == "Board game night"
    assert {"id", "title", "banner", "banner_url"} <= set(body["event"])
    assert body["chat_context"] == ctx
    assert body["reported"]["event"]["id"] == EV1 and body["reported"]["user"] is None


def test_details_message_report(db):
    db.tables["event_chats"].extend([_chat(41, sender=MIA), _chat(42)])
    ctx = [{"id": 41, "type": "chat", "sender_id": MIA, "sender_name": "Mia", "content": "Hi all",
            "created_at": "2026-10-28T18:00:40+00:00", "reported": False},
           {"id": 42, "type": "chat", "sender_id": TOM, "sender_name": "Tom", "content": "rude",
            "created_at": "2026-10-28T18:01:55+00:00", "reported": True}]
    _put(db, _report(1, "2026-10-01T10:00:00+00:00", target_type="message", event_id=EV1, reported_user_id=TOM,
                     message_id=42, origin="event_chat", reason="harassment_or_hate",
                     description="He keeps insulting guests.", chat_context=ctx))
    body = _detail(1)
    assert body["target_type"] == "message" and body["description"] == "He keeps insulting guests."
    assert body["reported"]["type"] == "message"
    assert body["reported"]["message"] == {"id": 42, "event_id": EV1}
    assert body["reported"]["user"]["id"] == TOM
    assert body["reported"]["event"] is None
    assert body["event"]["id"] == EV1 and body["event"]["title"] == "Board game night"
    assert body["chat_context"] == ctx
    assert [c["reported"] for c in body["chat_context"]] == [False, True]
    assert body["content_removed"] is False


def test_details_user_report_from_profile(db):
    _put(db, _report(1, "2026-10-01T10:00:00+00:00", target_type="user", event_id=None, reported_user_id=TOM,
                     origin="profile", reason="spam"))
    body = _detail(1)
    assert body["origin"] == "profile" and body["target_type"] == "user"
    assert body["event"] is None and body["chat_context"] is None
    assert body["reported"]["type"] == "user" and body["reported"]["user"]["id"] == TOM
    assert body["reported"]["event"] is None and body["reported"]["message"] is None
    assert body["content_removed"] is False


def test_details_deleted_reporter_is_null(db):
    _put(db, _report(1, "2026-10-01T10:00:00+00:00", reporter_id=None))
    assert _detail(1)["reporter"] is None


def test_details_deleted_event_gives_nulls(db):
    _put(db, _report(1, "2026-10-01T10:00:00+00:00", event_id=None, origin="event_chat", chat_context=[]))
    body = _detail(1)
    assert body["reported"]["event"] is None and body["event"] is None
    assert body["content_removed"] is True and body["reported_user_is_administrator"] is False  # deleted counts as removed


# content_removed (live)

def test_content_removed_true_for_removed_event(db):
    db.tables["events"][0]["removed_at"] = "2026-10-20T00:00:00+00:00"
    _put(db, _report(1, "2026-10-01T10:00:00+00:00"))
    assert _detail(1)["content_removed"] is True


def test_content_removed_false_for_live_event(db):
    _put(db, _report(1, "2026-10-01T10:00:00+00:00"))
    assert _detail(1)["content_removed"] is False


def test_content_removed_true_for_removed_message(db):
    db.tables["event_chats"].append(_chat(42, removed_at="2026-10-20T00:00:00+00:00"))
    _put(db, _report(1, "2026-10-01T10:00:00+00:00", target_type="message", reported_user_id=TOM,
                     message_id=42, origin="event_chat", chat_context=[]))
    assert _detail(1)["content_removed"] is True


def test_content_removed_false_for_live_message(db):
    db.tables["event_chats"].append(_chat(42))
    _put(db, _report(1, "2026-10-01T10:00:00+00:00", target_type="message", reported_user_id=TOM,
                     message_id=42, origin="event_chat", chat_context=[]))
    assert _detail(1)["content_removed"] is False


def test_content_removed_always_false_for_user_report(db):
    db.tables["events"][0]["removed_at"] = "2026-10-20T00:00:00+00:00"
    _put(db, _report(1, "2026-10-01T10:00:00+00:00", target_type="user", event_id=None, reported_user_id=TOM,
                     origin="profile"))
    assert _detail(1)["content_removed"] is False


# reported_user_is_administrator (live)

def test_admin_flag_true_when_reported_user_is_administrator(db):
    _put(db, _report(1, "2026-10-01T10:00:00+00:00", target_type="user", event_id=None, reported_user_id=ADM2,
                     origin="profile"))
    assert _detail(1)["reported_user_is_administrator"] is True


def test_admin_flag_true_when_message_author_is_administrator(db):
    db.tables["event_chats"].append(_chat(42, sender=ADM2))
    _put(db, _report(1, "2026-10-01T10:00:00+00:00", target_type="message", reported_user_id=ADM2,
                     message_id=42, origin="event_chat", chat_context=[]))
    assert _detail(1)["reported_user_is_administrator"] is True


def test_admin_flag_true_when_event_organizer_is_administrator(db):
    db.tables["events"][0]["created_by"] = ADM2
    _put(db, _report(1, "2026-10-01T10:00:00+00:00"))
    assert _detail(1)["reported_user_is_administrator"] is True


def test_admin_flag_is_computed_now_not_when_reported(db):
    _put(db, _report(1, "2026-10-01T10:00:00+00:00", target_type="user", event_id=None, reported_user_id=TOM,
                     origin="profile"))
    assert _detail(1)["reported_user_is_administrator"] is False
    next(p for p in db.tables["profiles"] if p["id"] == TOM)["role"] = "administrator"
    assert _detail(1)["reported_user_is_administrator"] is True


def test_admin_flag_false_for_regular_user_organizer_and_gone_user(db):
    _put(db, _report(1, "2026-10-01T10:00:00+00:00"),
         _report(2, "2026-10-01T11:00:00+00:00", target_type="user", event_id=None, reported_user_id=None,
                 origin="profile"))
    assert _detail(1)["reported_user_is_administrator"] is False
    assert _detail(2)["reported_user_is_administrator"] is False


# closed report

def test_closed_report_details_show_outcome_closer_and_time(db):
    _put(db, _report(1, "2026-10-01T10:00:00+00:00", status="action_taken", outcome="warned",
                     closed_by=ADM, closed_at="2026-10-29T08:12:30.004512+00:00"))
    body = _detail(1)
    assert body["status"] == "action_taken" and body["outcome"] == "warned"
    assert body["closed_at"] == "2026-10-29T08:12:30.004512+00:00"
    assert PERSON_KEYS <= set(body["closed_by"])
    assert body["closed_by"]["id"] == ADM and body["closed_by"]["username"] == "boss"


def test_dismissed_report_details(db):
    _put(db, _report(1, "2026-10-01T10:00:00+00:00", status="dismissed", outcome="dismissed",
                     closed_by=ADM2, closed_at="2026-10-29T08:00:00+00:00"))
    body = _detail(1)
    assert body["status"] == "dismissed" and body["outcome"] == "dismissed"
    assert body["closed_by"]["username"] == "boss2"


# 404

@pytest.mark.parametrize("rid", ["999", "0"])
def test_unknown_report_is_404_report_not_found(db, rid):
    _put(db, _report(1, "2026-10-01T10:00:00+00:00"))
    res = client.get(f"/api/admin/reports/{rid}")
    assert res.status_code == 404
    detail = res.json()["detail"]
    assert isinstance(detail, dict), res.text
    assert detail["code"] == "report_not_found" and isinstance(detail["message"], str)


# ---- admin only --------------------------------------------------------------

def _jwt(payload):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{enc({'alg': 'HS256'})}.{enc(payload)}.sig"


REPORT_READ_ENDPOINTS_235 = [
    ("GET", "/api/admin/reports/open"),
    ("GET", "/api/admin/reports"),
    ("GET", "/api/admin/reports?page=1&limit=20"),
    ("GET", "/api/admin/reports/1"),
]


def _as_user_account(mock_sb):
    app.dependency_overrides.clear()
    mock_sb.auth.get_user.return_value = MagicMock(user=SimpleNamespace(id=MIA))
    chain = MagicMock()
    chain.select.return_value = chain.eq.return_value = chain.single.return_value = chain
    chain.execute.return_value = MagicMock(data={"role": "user"})
    mock_sb.table.return_value = chain
    return {"Authorization": f"Bearer {_jwt({'sub': MIA, 'aal': 'aal2'})}"}


@pytest.mark.parametrize("method,url", REPORT_READ_ENDPOINTS_235)
@patch("app.core.dependencies.supabase")
def test_user_account_is_refused_on_every_report_read_endpoint(mock_sb, method, url):
    headers = _as_user_account(mock_sb)
    res = client.request(method, url, headers=headers)
    assert res.status_code == 403, f"{method} {url} should refuse a user account with 403, got {res.status_code}"


@patch("app.core.dependencies.supabase")
def test_report_list_refused_for_user_account(mock_sb):
    headers = _as_user_account(mock_sb)
    for url in ("/api/admin/reports", "/api/admin/reports/open"):
        res = client.get(url, headers=headers)
        assert res.status_code == 403, f"GET {url} returned {res.status_code}"


@pytest.mark.parametrize("url", ["/api/admin/reports/open", "/api/admin/reports", "/api/admin/reports/1"])
def test_unauthenticated_request_is_refused_like_other_admin_endpoints(url):
    app.dependency_overrides.clear()
    baseline = client.get("/api/admin/users").status_code
    assert baseline in (401, 403)
    res = client.get(url)
    assert res.status_code == baseline, f"GET {url} returned {res.status_code}, other admin endpoints {baseline}"


# ==== review follow-ups (F-001, F-002, F-004, F-006, F-007) ============================

import logging
import uuid

from app.services.admin_service import _build_user_summary
from app.services.removed_content import LOOKUP_CHUNK
from tests import _fake_supabase

ICO = "44444444-4444-4444-8444-444444444444"   # icon avatar, has a username
NOU = "55555555-5555-4555-8555-555555555555"   # no username, only a full name
ICON_PROFILE = {"id": ICO, "username": "iggy", "full_name": "Iggy Icon", "role": "user", "avatar_url": None,
                "avatar_kind": "icon", "icon_id": "fox", "visibility": "public",
                "created_at": "2026-01-01T00:00:00+00:00", "suspended_at": None}
NO_USERNAME_PROFILE = {"id": NOU, "username": None, "full_name": "Zed Nobody", "role": "user",
                       "avatar_url": "https://img/zed.png", "avatar_kind": "photo", "icon_id": None,
                       "visibility": "public", "created_at": "2026-01-01T00:00:00+00:00", "suspended_at": None}


def _profile_row(db, uid):
    return next(p for p in db.tables["profiles"] if p["id"] == uid)


# ---- (d) value assertions -----------------------------------------------------

def test_event_card_banner_equals_banner_url(db):
    _put(db, _report(1, "2026-10-01T10:00:00+00:00", origin="event_chat", chat_context=[]))
    for items in _both_lists():
        card = items[0]["reported"]["event"]
        assert card["banner"] == card["banner_url"] == "https://img/Board game night.jpg"
    body = _detail(1)
    assert body["event"]["banner"] == body["event"]["banner_url"] == "https://img/Board game night.jpg"
    assert body["reported"]["event"]["banner"] == "https://img/Board game night.jpg"


def test_person_objects_match_user_summary_incl_icon_avatar_and_no_username(db):
    db.tables["profiles"].extend([dict(ICON_PROFILE), dict(NO_USERNAME_PROFILE)])
    _put(db, _report(1, "2026-10-01T10:00:00+00:00", reporter_id=ICO, target_type="user", event_id=None,
                     reported_user_id=NOU, origin="profile"),
         _report(2, "2026-10-01T11:00:00+00:00", reporter_id=MIA, target_type="user", event_id=None,
                 reported_user_id=TOM, origin="profile"))
    expected = {uid: _build_user_summary(_profile_row(db, uid)) for uid in (ICO, NOU, MIA, TOM)}
    assert expected[MIA]["display_name"] == "mia"
    assert expected[NOU]["display_name"] == "Zed Nobody" and expected[NOU]["username"] is None
    assert expected[ICO]["avatar_kind"] == "icon" and expected[ICO]["icon_id"] == "fox"
    for items in _both_lists():
        by_id = {i["id"]: i for i in items}
        assert by_id[1]["reporter"] == expected[ICO]
        assert by_id[1]["reported"]["user"] == expected[NOU]
        assert by_id[2]["reporter"] == expected[MIA]
        assert by_id[2]["reported"]["user"] == expected[TOM]
    body = _detail(1)
    assert body["reporter"] == expected[ICO] and body["reported"]["user"] == expected[NOU]


def test_details_closed_by_is_a_full_person_summary(db):
    _put(db, _report(1, "2026-10-01T10:00:00+00:00", **CLOSED))
    assert _detail(1)["closed_by"] == _build_user_summary(_profile_row(db, ADM))


# ---- (e) F-001: unchunked in_ lookups ------------------------------------------

@pytest.fixture
def in_spy(monkeypatch):
    lengths = []
    original = _fake_supabase.FakeQuery.in_

    def spy(self, col, vals):
        vals = list(vals)
        lengths.append(len(vals))
        if len(vals) > LOOKUP_CHUNK:
            raise AssertionError(f"in_({col!r}) got {len(vals)} ids, more than LOOKUP_CHUNK={LOOKUP_CHUNK}")
        return original(self, col, vals)

    monkeypatch.setattr(_fake_supabase.FakeQuery, "in_", spy)
    return lengths


def _uid(prefix, n):
    return str(uuid.UUID(int=(prefix << 100) + n))


def test_open_list_with_hundreds_of_reports_chunks_every_in_lookup(db, in_spy):
    n = 350
    for i in range(1, n + 1):
        db.tables["profiles"].append(_profile(_uid(1, i), f"reporter{i}"))
        db.tables["profiles"].append(_profile(_uid(2, i), f"reported{i}"))
        db.tables["events"].append(_event(_uid(3, i), f"event{i}"))
    _put(db, *[_report(i, f"2026-10-01T10:00:{i % 60:02d}+00:00", reporter_id=_uid(1, i), event_id=_uid(3, i),
                       reported_user_id=_uid(2, i), target_type="event" if i % 2 else "user",
                       origin="event_details" if i % 2 else "profile")
               for i in range(1, n + 1)])
    res = client.get("/api/admin/reports/open")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == n and len(body["items"]) == n
    assert sorted(_ids(body["items"])) == list(range(1, n + 1))
    for item in body["items"]:
        i = item["id"]
        assert item["reporter"]["id"] == _uid(1, i) and item["reporter"]["username"] == f"reporter{i}"
        if item["target_type"] == "event":
            assert item["reported"]["event"]["id"] == _uid(3, i)
            assert item["reported"]["event"]["title"] == f"event{i}"
        else:
            assert item["reported"]["user"]["id"] == _uid(2, i)
            assert item["reported"]["user"]["username"] == f"reported{i}"
    assert in_spy and max(in_spy) <= LOOKUP_CHUNK
    assert max(in_spy) == LOOKUP_CHUNK  # the big lists really were split at the chunk size


def test_small_lists_still_use_one_in_query_per_lookup(db, in_spy):
    _put(db, _report(1, "2026-10-01T10:00:00+00:00"),
         _report(2, "2026-10-02T10:00:00+00:00", reporter_id=ANA, event_id=EV2))
    assert client.get("/api/admin/reports/open").status_code == 200
    assert len(in_spy) == 2  # one profiles lookup, one events lookup (plus the reports query itself)
    in_spy.clear()
    assert client.get("/api/admin/reports").status_code == 200
    assert len(in_spy) == 2


def test_empty_open_list_makes_no_in_query(db, in_spy):
    assert client.get("/api/admin/reports/open").status_code == 200
    assert in_spy == []


# ---- (f) F-002: server row cap must not shrink the total -----------------------

def test_open_total_is_the_exact_count_when_rows_are_capped(db, monkeypatch, caplog):
    _put(db, *[_report(i, f"2026-10-01T10:{i:02d}:00+00:00") for i in range(1, 13)])
    original = _fake_supabase.FakeQuery.execute
    cap = 5

    def capped(self):
        res = original(self)
        if self.name == "reports" and self.want_count and self.action == "select":
            res.data = res.data[:cap]  # like PostgREST max-rows: fewer rows, exact count kept
        return res

    monkeypatch.setattr(_fake_supabase.FakeQuery, "execute", capped)
    with caplog.at_level(logging.WARNING, logger="app.services.admin_report_service"):
        res = client.get("/api/admin/reports/open")
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["items"]) == cap
    assert body["total"] == 12
    assert any(r.levelno == logging.WARNING and "truncated" in r.getMessage() for r in caplog.records)


def test_open_total_without_cap_logs_no_truncation_warning(db, caplog):
    _put(db, _report(1, "2026-10-01T10:00:00+00:00"))
    with caplog.at_level(logging.WARNING, logger="app.services.admin_report_service"):
        assert client.get("/api/admin/reports/open").json()["total"] == 1
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_open_total_falls_back_to_item_count_when_count_is_missing(db, monkeypatch):
    _put(db, *[_report(i, f"2026-10-01T10:{i:02d}:00+00:00") for i in range(1, 4)])
    original = _fake_supabase.FakeQuery.execute

    def no_count(self):
        res = original(self)
        if self.name == "reports":
            res.count = None
        return res

    monkeypatch.setattr(_fake_supabase.FakeQuery, "execute", no_count)
    body = client.get("/api/admin/reports/open").json()
    assert body["total"] == 3 and len(body["items"]) == 3


# ---- (g) F-004: report_id bounds ----------------------------------------------

def test_report_id_overflowing_bigint_is_422(db):
    assert client.get("/api/admin/reports/99999999999999999999").status_code == 422
    assert client.get("/api/admin/reports/9223372036854775808").status_code == 422
    assert client.get("/api/admin/reports/99999999999999999999/").status_code == 422


def test_report_id_at_the_bigint_limit_is_404_and_zero_or_negative_stay_404(db):
    for rid in ("9223372036854775807", "0", "-1"):
        res = client.get(f"/api/admin/reports/{rid}")
        assert res.status_code == 404, (rid, res.text)
        assert res.json()["detail"]["code"] == "report_not_found"


# ---- (h) F-006: failure branch -------------------------------------------------

FAILURE_URLS = ["/api/admin/reports/open", "/api/admin/reports", "/api/admin/reports/1"]


def _break_reports_queries(monkeypatch):
    original = _fake_supabase.FakeQuery.execute

    def boom(self):
        if self.name == "reports":
            raise RuntimeError("database is down")
        return original(self)

    monkeypatch.setattr(_fake_supabase.FakeQuery, "execute", boom)


@pytest.mark.parametrize("url", FAILURE_URLS)
def test_load_failure_is_500_with_fixed_detail_and_logged_traceback(db, monkeypatch, caplog, url):
    _put(db, _report(1, "2026-10-01T10:00:00+00:00"))
    _break_reports_queries(monkeypatch)
    with caplog.at_level(logging.ERROR, logger="app.services.admin_report_service"):
        res = client.get(url)
    assert res.status_code == 500
    assert res.json() == {"detail": "Could not load reports."}
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert errors, "an ERROR record was expected"
    assert errors[0].exc_info and errors[0].exc_info[0] is RuntimeError
    assert "database is down" in caplog.text and "Traceback" in caplog.text


@pytest.mark.parametrize("url", ["/api/admin/reports/open", "/api/admin/reports"])
def test_lookup_failure_inside_a_list_is_also_500(db, monkeypatch, caplog, url):
    _put(db, _report(1, "2026-10-01T10:00:00+00:00"))
    original = _fake_supabase.FakeQuery.execute

    def boom(self):
        if self.name == "events":
            raise RuntimeError("events lookup failed")
        return original(self)

    monkeypatch.setattr(_fake_supabase.FakeQuery, "execute", boom)
    with caplog.at_level(logging.ERROR, logger="app.services.admin_report_service"):
        res = client.get(url)
    assert res.status_code == 500 and res.json()["detail"] == "Could not load reports."
    assert any(r.exc_info for r in caplog.records if r.levelno == logging.ERROR)


def test_unknown_report_stays_404_and_is_not_logged_as_a_failure(db, caplog):
    with caplog.at_level(logging.ERROR, logger="app.services.admin_report_service"):
        res = client.get("/api/admin/reports/12345")
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "report_not_found"
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


# ---- (a)(b)(c) F-007: the real require_admin chain, with and without trailing slash ----

ALL_REPORT_URLS = ["/api/admin/reports/open", "/api/admin/reports/open/",
                   "/api/admin/reports", "/api/admin/reports/",
                   "/api/admin/reports/1", "/api/admin/reports/1/"]


def _real_chain(mock_sb, role, aal):
    """Real require_admin: only Supabase auth and the role lookup (app.core.dependencies) are mocked."""
    app.dependency_overrides.clear()
    mock_sb.auth.get_user.return_value = MagicMock(user=SimpleNamespace(id=ADM))
    chain = MagicMock()
    chain.select.return_value = chain.eq.return_value = chain.single.return_value = chain
    chain.execute.return_value = MagicMock(data={"role": role})
    mock_sb.table.return_value = chain
    return {"Authorization": f"Bearer {_jwt({'sub': ADM, 'aal': aal})}"}


@pytest.mark.parametrize("url", ALL_REPORT_URLS)
@patch("app.core.dependencies.supabase")
def test_real_chain_administrator_with_mfa_gets_200(mock_sb, db, url):
    _put(db, _report(1, "2026-10-01T10:00:00+00:00"))
    headers = _real_chain(mock_sb, "administrator", "aal2")
    res = client.get(url, headers=headers, follow_redirects=False)  # a redirect would drop the MFA token
    assert res.status_code == 200, f"{url}: {res.status_code} {res.text}"


@pytest.mark.parametrize("url", ALL_REPORT_URLS)
@patch("app.core.dependencies.supabase")
def test_real_chain_administrator_without_mfa_gets_403(mock_sb, db, url):
    _put(db, _report(1, "2026-10-01T10:00:00+00:00"))
    headers = _real_chain(mock_sb, "administrator", "aal1")
    res = client.get(url, headers=headers, follow_redirects=False)
    assert res.status_code == 403, f"{url}: {res.status_code} {res.text}"
    assert "MFA" in res.json()["detail"]


@pytest.mark.parametrize("url", ALL_REPORT_URLS)
@patch("app.core.dependencies.supabase")
def test_real_chain_user_role_gets_403_even_with_mfa(mock_sb, db, url):
    _put(db, _report(1, "2026-10-01T10:00:00+00:00"))
    headers = _real_chain(mock_sb, "user", "aal2")
    res = client.get(url, headers=headers, follow_redirects=False)
    assert res.status_code == 403, f"{url}: {res.status_code} {res.text}"


@pytest.mark.parametrize("url", ALL_REPORT_URLS)
def test_unauthenticated_request_is_401_or_403_and_matches_other_admin_endpoints(url):
    app.dependency_overrides.clear()
    baseline = client.get("/api/admin/users", follow_redirects=False).status_code
    res = client.get(url, follow_redirects=False)
    assert res.status_code in (401, 403)
    assert res.status_code == baseline, f"GET {url} returned {res.status_code}, other admin endpoints {baseline}"


# ---- review follow-ups F-005, F-003, F-008 ---------------------------------------

def _msg_report(rid=1, message_id=42, **kw):
    return _report(rid, "2026-10-01T10:00:00+00:00", target_type="message", reported_user_id=TOM,
                   message_id=message_id, origin="event_chat", chat_context=[], **kw)


def test_content_removed_true_when_event_was_deleted_event_id_null(db):
    _put(db, _report(1, "2026-10-01T10:00:00+00:00", event_id=None))
    assert _detail(1)["content_removed"] is True


def test_content_removed_true_when_event_row_is_missing_though_event_id_set(db):
    db.tables["events"] = [e for e in db.tables["events"] if e["id"] != EV1]
    _put(db, _report(1, "2026-10-01T10:00:00+00:00"))
    assert _detail(1)["content_removed"] is True


def test_content_removed_true_when_message_was_hard_deleted(db):
    _put(db, _msg_report())  # no event_chats row for message 42
    assert _detail(1)["content_removed"] is True


def test_content_removed_false_for_live_event_and_live_message_together(db):
    db.tables["event_chats"].append(_chat(42))
    _put(db, _report(1, "2026-10-01T10:00:00+00:00"), _msg_report(2))
    assert _detail(1)["content_removed"] is False
    assert _detail(2)["content_removed"] is False


def test_content_removed_false_for_user_report_with_deleted_user(db):
    _put(db, _report(1, "2026-10-01T10:00:00+00:00", target_type="user", event_id=None, reported_user_id=None,
                     origin="profile"))
    assert _detail(1)["content_removed"] is False


def test_content_removed_still_true_for_removed_event_and_message(db):
    db.tables["events"][1]["removed_at"] = "2026-10-20T00:00:00+00:00"
    db.tables["event_chats"].append(_chat(42, removed_at="2026-10-20T00:00:00+00:00"))
    _put(db, _report(1, "2026-10-01T10:00:00+00:00", event_id=EV2), _msg_report(2))
    assert _detail(1)["content_removed"] is True
    assert _detail(2)["content_removed"] is True


def test_list_items_do_not_carry_content_removed(db):
    _put(db, _report(1, "2026-10-01T10:00:00+00:00", event_id=None), _msg_report(2))
    for items in _both_lists():
        assert all("content_removed" not in i for i in items)


def test_all_list_page_10000_is_200_and_empty_with_correct_totals(db):
    _many(db, 5)
    res = client.get("/api/admin/reports?page=10000&limit=20")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["items"] == [] and body["total"] == 5 and body["total_pages"] == 1 and body["page"] == 10000


def test_all_list_page_10001_is_422(db):
    assert client.get("/api/admin/reports?page=10001").status_code == 422


def _components():
    res = client.get("/openapi.json")
    assert res.status_code == 200
    return res.json()["components"]["schemas"]


def _enum_of(prop):
    if "enum" in prop:
        return prop["enum"]
    for part in prop.get("anyOf", []) + prop.get("allOf", []):
        if "enum" in part:
            return part["enum"]
    return None


def test_openapi_exposes_report_vocabularies_as_enums():
    schemas = _components()
    for name in ("AdminReportItem", "AdminReportDetailResponse"):
        props = schemas[name]["properties"]
        assert _enum_of(props["status"]) == ["open", "dismissed", "action_taken"], name
        assert _enum_of(props["target_type"]) == ["event", "user", "message"], name
        assert _enum_of(props["origin"]) == ["event_details", "profile", "event_chat"], name
        assert _enum_of(props["reason"]) == ["spam", "inappropriate_content", "harassment_or_hate",
                                             "scam_or_fraud", "misleading_event", "other"], name
    outcome = schemas["AdminReportDetailResponse"]["properties"]["outcome"]
    assert _enum_of(outcome) == ["dismissed", "warned", "content_removed", "suspended"]
    assert _enum_of(schemas["ReportedContent"]["properties"]["type"]) == ["event", "user", "message"]
