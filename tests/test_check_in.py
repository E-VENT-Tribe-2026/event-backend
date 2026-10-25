from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.core.dependencies import get_current_onboarded_user
from app.core.user_rate_limit import CHECK_IN_WRONG_CODE_LIMIT
from app.services.check_in_service import (
    check_in,
    get_event_check_in_code,
    list_event_check_ins,
)

client = TestClient(app)
EVENT_ID = "11111111-1111-1111-1111-111111111111"
ORG = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
PART = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
OTHER = "cccccccc-cccc-cccc-cccc-cccccccccccc"
CODE = "482913"


def _start(hours_from_now: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours_from_now)).isoformat()


def _event(**overrides):
    row = {
        "id": EVENT_ID,
        "title": "Jazz Night",
        "status": "active",
        "start_datetime": _start(1),
        "created_by": ORG,
        "check_in_code": CODE,
        "check_in_qr_content": CODE,
    }
    row.update(overrides)
    return row


def _chain(data=None):
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.limit.return_value = chain
    chain.order.return_value = chain
    chain.insert.return_value = chain
    chain.execute.return_value = MagicMock(data=data)
    return chain


def _router(tables: dict):
    sb = MagicMock()
    sb.table.side_effect = lambda name: tables[name]
    return sb


class TestGetCheckInCode:
    @patch("app.services.check_in_service.supabase")
    def test_organizer_receives_code_and_qr(self, mock_sb):
        mock_sb.table.return_value = _chain([_event()])
        result = get_event_check_in_code(EVENT_ID, ORG)
        assert result == {"event_id": EVENT_ID, "code": CODE, "qr_content": CODE}

    @patch("app.services.check_in_service.supabase")
    def test_participant_is_refused(self, mock_sb):
        mock_sb.table.return_value = _chain([_event()])
        try:
            get_event_check_in_code(EVENT_ID, PART)
            assert False
        except HTTPException as exc:
            assert exc.status_code == 403
            assert "organizer" in exc.detail.lower()


class TestCheckIn:
    def _setup(self, mock_sb, event=None, participants=None, existing=None, inserted=None):
        tables = {
            "events": _chain([event or _event()]),
            "event_participants": _chain([{"user_id": PART}, {"user_id": ORG}]),
            "event_check_ins": _chain(existing if existing is not None else []),
        }
        if inserted is not None:
            tables["event_check_ins"].execute.side_effect = [
                MagicMock(data=existing or []),
                MagicMock(data=[inserted]),
            ]
        if participants is not None:
            tables["event_participants"] = _chain(participants)
        mock_sb.table.side_effect = lambda name: tables[name]
        return tables

    @patch("app.services.check_in_service.supabase")
    def test_participant_checks_in_with_code(self, mock_sb):
        self._setup(
            mock_sb,
            inserted={"user_id": PART, "checked_in_at": "2026-11-01T18:05:00+00:00"},
        )
        result = check_in(EVENT_ID, PART, code="482-913")
        assert result["checked_in"] is True
        assert result["already_checked_in"] is False
        assert result["checked_in_at"] == "2026-11-01T18:05:00+00:00"

    @patch("app.services.check_in_service.supabase")
    def test_participant_checks_in_with_qr_content(self, mock_sb):
        self._setup(
            mock_sb,
            inserted={"user_id": PART, "checked_in_at": "2026-11-01T18:05:00+00:00"},
        )
        result = check_in(EVENT_ID, PART, qr_content=CODE)
        assert result["already_checked_in"] is False

    @patch("app.services.check_in_service.supabase")
    def test_already_checked_in_changes_nothing(self, mock_sb):
        self._setup(mock_sb, existing=[{"checked_in_at": "2026-11-01T18:00:00+00:00"}])
        result = check_in(EVENT_ID, PART, code=CODE)
        assert result["already_checked_in"] is True
        assert result["checked_in"] is True

    @patch("app.services.check_in_service.supabase")
    def test_non_participant_is_refused(self, mock_sb):
        self._setup(mock_sb, participants=[{"user_id": PART}])
        try:
            check_in(EVENT_ID, OTHER, code=CODE)
            assert False
        except HTTPException as exc:
            assert exc.status_code == 403
            assert "participants" in exc.detail.lower()

    @patch("app.services.check_in_service.supabase")
    def test_wrong_code_is_refused(self, mock_sb):
        self._setup(mock_sb)
        try:
            check_in(EVENT_ID, PART, code="000000")
            assert False
        except HTTPException as exc:
            assert exc.status_code == 400
            assert "incorrect" in exc.detail.lower()

    @patch("app.services.check_in_service.supabase")
    def test_outside_window_before_is_refused(self, mock_sb):
        self._setup(mock_sb, event=_event(start_datetime=_start(4)))
        try:
            check_in(EVENT_ID, PART, code=CODE)
            assert False
        except HTTPException as exc:
            assert exc.status_code == 400
            assert "three hours" in exc.detail.lower()

    @patch("app.services.check_in_service.supabase")
    def test_outside_window_after_is_refused(self, mock_sb):
        self._setup(mock_sb, event=_event(start_datetime=_start(-13)))
        try:
            check_in(EVENT_ID, PART, code=CODE)
            assert False
        except HTTPException as exc:
            assert exc.status_code == 400
            assert "twelve hours" in exc.detail.lower()

    @patch("app.services.check_in_service.record_user_rate_hit")
    @patch("app.services.check_in_service.raise_if_user_rate_limited")
    @patch("app.services.check_in_service.supabase")
    def test_too_many_wrong_codes_are_refused(self, mock_sb, mock_raise, _record):
        self._setup(mock_sb)
        mock_raise.side_effect = HTTPException(
            status_code=429,
            detail="Too many incorrect check-in codes. Please wait a moment and try again.",
        )
        try:
            check_in(EVENT_ID, PART, code="000000")
            assert False
        except HTTPException as exc:
            assert exc.status_code == 429
            assert "incorrect check-in codes" in exc.detail.lower()


class TestListCheckIns:
    @patch("app.services.check_in_service.get_user_summaries")
    @patch("app.services.check_in_service.supabase")
    def test_organizer_sees_times_and_counts(self, mock_sb, mock_summaries):
        mock_summaries.return_value = {
            PART: {"id": PART, "username": "pat", "full_name": "Pat", "display_name": "pat",
                   "avatar_kind": "icon", "icon_id": None, "avatar_url": None},
        }
        tables = {
            "events": _chain([_event()]),
            "event_participants": _chain([{"user_id": PART}, {"user_id": ORG}, {"user_id": OTHER}]),
            "event_check_ins": _chain([{"user_id": PART, "checked_in_at": "2026-11-01T18:05:00+00:00"}]),
        }
        mock_sb.table.side_effect = lambda name: tables[name]
        result = list_event_check_ins(EVENT_ID, ORG)
        assert result["checked_in_count"] == 1
        assert result["participant_count"] == 3
        assert result["include_times"] is True
        assert result["items"][0]["checked_in_at"] == "2026-11-01T18:05:00+00:00"
        assert result["viewer_checked_in"] is False

    @patch("app.services.check_in_service.get_user_summaries")
    @patch("app.services.check_in_service.supabase")
    def test_participant_does_not_see_times(self, mock_sb, mock_summaries):
        mock_summaries.return_value = {PART: {"id": PART, "username": "pat"}}
        tables = {
            "events": _chain([_event()]),
            "event_participants": _chain([{"user_id": PART}, {"user_id": ORG}]),
            "event_check_ins": _chain([{"user_id": PART, "checked_in_at": "2026-11-01T18:05:00+00:00"}]),
        }
        mock_sb.table.side_effect = lambda name: tables[name]
        result = list_event_check_ins(EVENT_ID, PART)
        assert result["include_times"] is False
        assert "checked_in_at" not in result["items"][0]
        assert result["viewer_checked_in"] is True

    @patch("app.services.check_in_service.supabase")
    def test_outsider_is_refused(self, mock_sb):
        tables = {
            "events": _chain([_event()]),
            "event_participants": _chain([{"user_id": PART}]),
        }
        mock_sb.table.side_effect = lambda name: tables[name]
        try:
            list_event_check_ins(EVENT_ID, OTHER)
            assert False
        except HTTPException as exc:
            assert exc.status_code == 403


class TestCheckInRoutes:
    def _as(self, user_id):
        app.dependency_overrides[get_current_onboarded_user] = lambda: SimpleNamespace(id=user_id)

    def teardown_method(self):
        app.dependency_overrides.pop(get_current_onboarded_user, None)

    def test_get_code_route(self):
        self._as(ORG)
        with patch(
            "app.api.v1.event_routes.get_event_check_in_code",
            return_value={"event_id": EVENT_ID, "code": CODE, "qr_content": CODE},
        ):
            res = client.get(f"/api/events/{EVENT_ID}/check-in-code", headers={"Authorization": "Bearer t"})
        assert res.status_code == 200
        assert res.json()["code"] == CODE
        assert res.json()["qr_content"] == CODE

    def test_post_check_in_route(self):
        self._as(PART)
        with patch(
            "app.api.v1.event_routes.record_event_check_in",
            return_value={"checked_in": True, "already_checked_in": False, "checked_in_at": "t"},
        ) as mock_check:
            res = client.post(
                f"/api/events/{EVENT_ID}/check-in",
                json={"code": CODE},
                headers={"Authorization": "Bearer t"},
            )
        assert res.status_code == 200
        mock_check.assert_called_once_with(EVENT_ID, PART, code=CODE, qr_content=None)

    def test_get_check_ins_route(self):
        self._as(PART)
        payload = {
            "event_id": EVENT_ID,
            "checked_in_count": 1,
            "participant_count": 2,
            "viewer_checked_in": True,
            "include_times": False,
            "items": [{"user": {"id": PART, "username": "pat"}}],
        }
        with patch("app.api.v1.event_routes.list_event_check_ins", return_value=payload):
            res = client.get(f"/api/events/{EVENT_ID}/check-ins", headers={"Authorization": "Bearer t"})
        assert res.status_code == 200
        assert "checked_in_at" not in res.json()["items"][0]

    def test_event_detail_does_not_leak_code(self):
        with patch(
            "app.api.v1.event_routes.get_event",
            return_value={"id": EVENT_ID, "title": "Jazz Night", "created_by": ORG},
        ), patch("app.api.v1.event_routes.attach_organizers"):
            res = client.get(f"/api/events/{EVENT_ID}")
        assert res.status_code == 200
        assert "check_in_code" not in res.json()
        assert "check_in_qr_content" not in res.json()


class TestWrongCodeLimitUsesSharedLimiter:
    def test_limit_constant_matches_existing_style(self):
        assert CHECK_IN_WRONG_CODE_LIMIT == 10
