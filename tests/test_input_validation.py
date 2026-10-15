"""FR 12.4 Input Validation and Injection Prevention.

Covers:
- server-side limits for profile biography, event title, event description and
  chat messages, enforced on the API even when a request skips the screens;
- valid values are still passed through and saved;
- search text cannot change the shape of LIKE/ILIKE patterns.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.dependencies import get_current_onboarded_user, require_admin
from app.core.input_limits import (
    BIO_MAX_LENGTH,
    EVENT_TITLE_MIN_LENGTH,
    EVENT_TITLE_MAX_LENGTH,
    EVENT_DESCRIPTION_MAX_LENGTH,
    CHAT_MESSAGE_MAX_LENGTH,
    SEARCH_TEXT_MAX_LENGTH,
)
from app.utils.schema_validators import validate_text_value
from app.utils.query_safety import escape_like, like_contains

client = TestClient(app)
AUTH = {"Authorization": "Bearer token"}
EVENT_ID = "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture
def as_user():
    app.dependency_overrides[get_current_onboarded_user] = lambda: SimpleNamespace(id="u1")
    yield
    app.dependency_overrides.pop(get_current_onboarded_user, None)


@pytest.fixture
def as_admin():
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id="admin1")
    yield
    app.dependency_overrides.pop(require_admin, None)


# ────────────────────────────────────────────────────────────────────────────
# Shared text rule
# ────────────────────────────────────────────────────────────────────────────

class TestValidateTextValue:
    def test_strips_outer_whitespace(self):
        assert validate_text_value("  hi  ", field_label="X", max_length=10) == "hi"

    def test_counts_length_after_stripping(self):
        assert validate_text_value(" " + "a" * 10 + " ", field_label="X", max_length=10) == "a" * 10

    def test_refuses_over_max(self):
        with pytest.raises(ValueError, match="at most 10"):
            validate_text_value("a" * 11, field_label="X", max_length=10)

    def test_refuses_under_min(self):
        with pytest.raises(ValueError, match="at least 3"):
            validate_text_value("ab", field_label="X", min_length=3, max_length=10)

    def test_refuses_only_spaces_when_required(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_text_value("   ", field_label="X", min_length=1, max_length=10)

    @pytest.mark.parametrize("value", [123, 1.5, True, ["a"], {"a": 1}])
    def test_refuses_non_text(self, value):
        with pytest.raises(ValueError, match="must be text"):
            validate_text_value(value, field_label="X", max_length=10)

    @pytest.mark.parametrize("bad", ["\x00", "\x1b", "\x07", "\x7f", "\x9f"])
    def test_refuses_control_characters(self, bad):
        with pytest.raises(ValueError, match="not allowed"):
            validate_text_value(f"a{bad}b", field_label="X", max_length=10)

    def test_allows_newlines_and_tabs_in_multiline_text(self):
        assert validate_text_value("a\nb\r\nc\td", field_label="X", max_length=20) == "a\nb\r\nc\td"

    def test_refuses_newline_in_single_line_text(self):
        with pytest.raises(ValueError, match="single line"):
            validate_text_value("a\nb", field_label="X", max_length=10, allow_newlines=False)

    def test_keeps_unicode_and_emoji(self):
        assert validate_text_value("Grüße 🎉 नमस्ते", field_label="X", max_length=50) == "Grüße 🎉 नमस्ते"

    def test_sql_looking_text_is_just_text(self):
        text = "'; DROP TABLE events; --"
        assert validate_text_value(text, field_label="X", max_length=50) == text


# ────────────────────────────────────────────────────────────────────────────
# Profile biography — PUT /api/profile/me
# ────────────────────────────────────────────────────────────────────────────

class TestBioValidation:
    @patch("app.api.v1.profile_routes.update_profile")
    def test_refuses_bio_over_limit(self, mock_update, as_user):
        res = client.put("/api/profile/me", json={"bio": "a" * (BIO_MAX_LENGTH + 1)}, headers=AUTH)
        assert res.status_code == 422
        mock_update.assert_not_called()

    @patch("app.api.v1.profile_routes.update_profile")
    def test_refuses_bio_with_control_characters(self, mock_update, as_user):
        res = client.put("/api/profile/me", json={"bio": "hello\u0000world"}, headers=AUTH)
        assert res.status_code == 422
        mock_update.assert_not_called()

    @patch("app.api.v1.profile_routes.update_profile")
    def test_refuses_non_text_bio(self, mock_update, as_user):
        res = client.put("/api/profile/me", json={"bio": {"$ne": ""}}, headers=AUTH)
        assert res.status_code == 422
        mock_update.assert_not_called()

    @patch("app.api.v1.profile_routes.update_profile")
    def test_saves_valid_bio_at_limit(self, mock_update, as_user):
        mock_update.return_value = {"id": "u1"}
        bio = "line one\nline two " + "a" * (BIO_MAX_LENGTH - 18)
        assert len(bio) == BIO_MAX_LENGTH
        res = client.put("/api/profile/me", json={"bio": bio}, headers=AUTH)
        assert res.status_code == 200
        mock_update.assert_called_once_with("u1", {"bio": bio})

    @patch("app.api.v1.profile_routes.update_profile")
    def test_empty_bio_clears_it(self, mock_update, as_user):
        mock_update.return_value = {"id": "u1"}
        res = client.put("/api/profile/me", json={"bio": "   "}, headers=AUTH)
        assert res.status_code == 200
        mock_update.assert_called_once_with("u1", {"bio": ""})

    @patch("app.api.v1.profile_routes.update_profile")
    def test_update_without_bio_is_unaffected(self, mock_update, as_user):
        mock_update.return_value = {"id": "u1"}
        res = client.put("/api/profile/me", json={"interests": ["music"]}, headers=AUTH)
        assert res.status_code == 200
        mock_update.assert_called_once_with("u1", {"interests": ["music"]})


# ────────────────────────────────────────────────────────────────────────────
# Event title and description — POST /api/events/, PUT /api/events/{id}
# ────────────────────────────────────────────────────────────────────────────

def _event_body(**overrides):
    body = {
        "title": "Board games night",
        "description": "Bring a game.",
        "start_datetime": "2026-11-01T18:00:00Z",
        "end_datetime": "2026-11-01T21:00:00Z",
    }
    body.update(overrides)
    return body


class TestEventCreateValidation:
    @pytest.mark.parametrize("title", [
        "a" * (EVENT_TITLE_MIN_LENGTH - 1),
        "a" * (EVENT_TITLE_MAX_LENGTH + 1),
        "     ",
        "Line one\nLine two",
        "Party\x1b[31m",
        None,
        42,
    ])
    @patch("app.api.v1.event_routes.create_event")
    def test_refuses_bad_title(self, mock_create, title, as_user):
        res = client.post("/api/events/", json=_event_body(title=title), headers=AUTH)
        assert res.status_code == 422
        mock_create.assert_not_called()

    @patch("app.api.v1.event_routes.create_event")
    def test_refuses_missing_title(self, mock_create, as_user):
        body = _event_body()
        del body["title"]
        res = client.post("/api/events/", json=body, headers=AUTH)
        assert res.status_code == 422
        mock_create.assert_not_called()

    @pytest.mark.parametrize("description", [
        "a" * (EVENT_DESCRIPTION_MAX_LENGTH + 1),
        "bad\x00byte",
    ])
    @patch("app.api.v1.event_routes.create_event")
    def test_refuses_bad_description(self, mock_create, description, as_user):
        res = client.post("/api/events/", json=_event_body(description=description), headers=AUTH)
        assert res.status_code == 422
        mock_create.assert_not_called()

    @patch("app.api.v1.event_routes.create_event")
    def test_saves_valid_event_at_limits(self, mock_create, as_user):
        mock_create.return_value = {"id": EVENT_ID}
        title = "T" * EVENT_TITLE_MAX_LENGTH
        description = "Para 1\n\nPara 2\t" + "d" * (EVENT_DESCRIPTION_MAX_LENGTH - 15)
        assert len(description) == EVENT_DESCRIPTION_MAX_LENGTH
        res = client.post("/api/events/", json=_event_body(title=title, description=description), headers=AUTH)
        assert res.status_code == 200
        sent = mock_create.call_args.args[1]
        assert sent["title"] == title
        assert sent["description"] == description

    @patch("app.api.v1.event_routes.create_event")
    def test_trims_title_and_allows_missing_description(self, mock_create, as_user):
        mock_create.return_value = {"id": EVENT_ID}
        body = _event_body(title="  Picnic  ")
        del body["description"]
        res = client.post("/api/events/", json=body, headers=AUTH)
        assert res.status_code == 200
        sent = mock_create.call_args.args[1]
        assert sent["title"] == "Picnic"
        assert sent["description"] is None


class TestEventUpdateValidation:
    @patch("app.api.v1.event_routes._update_event_side_effects")
    @patch("app.api.v1.event_routes.update_event")
    def test_refuses_title_over_limit(self, mock_update, _side, as_user):
        res = client.put(f"/api/events/{EVENT_ID}", json={"title": "a" * (EVENT_TITLE_MAX_LENGTH + 1)}, headers=AUTH)
        assert res.status_code == 422
        mock_update.assert_not_called()

    @patch("app.api.v1.event_routes._update_event_side_effects")
    @patch("app.api.v1.event_routes.update_event")
    def test_refuses_explicit_null_title(self, mock_update, _side, as_user):
        res = client.put(f"/api/events/{EVENT_ID}", json={"title": None}, headers=AUTH)
        assert res.status_code == 422
        mock_update.assert_not_called()

    @patch("app.api.v1.event_routes._update_event_side_effects")
    @patch("app.api.v1.event_routes.update_event")
    def test_refuses_description_over_limit(self, mock_update, _side, as_user):
        res = client.put(
            f"/api/events/{EVENT_ID}",
            json={"description": "a" * (EVENT_DESCRIPTION_MAX_LENGTH + 1)},
            headers=AUTH,
        )
        assert res.status_code == 422
        mock_update.assert_not_called()

    @patch("app.api.v1.event_routes._update_event_side_effects")
    @patch("app.api.v1.event_routes.update_event")
    def test_partial_update_without_title_still_works(self, mock_update, _side, as_user):
        mock_update.return_value = ({"id": EVENT_ID}, {}, {})
        res = client.put(f"/api/events/{EVENT_ID}", json={"max_capacity": 30}, headers=AUTH)
        assert res.status_code == 200
        assert mock_update.call_args.args[2] == {"max_capacity": 30}

    @patch("app.api.v1.event_routes._update_event_side_effects")
    @patch("app.api.v1.event_routes.update_event")
    def test_description_can_be_cleared(self, mock_update, _side, as_user):
        mock_update.return_value = ({"id": EVENT_ID}, {}, {})
        res = client.put(f"/api/events/{EVENT_ID}", json={"description": None}, headers=AUTH)
        assert res.status_code == 200
        assert mock_update.call_args.args[2] == {"description": None}


# ────────────────────────────────────────────────────────────────────────────
# Chat messages — POST / PUT /api/chats/...
# ────────────────────────────────────────────────────────────────────────────

class TestChatMessageValidation:
    @pytest.mark.parametrize("content", [
        "",
        "    ",
        "a" * (CHAT_MESSAGE_MAX_LENGTH + 1),
        "hi\x00there",
        123,
    ])
    @patch("app.api.v1.chat_routes.send_message")
    def test_send_refuses_bad_content(self, mock_send, content, as_user):
        res = client.post(f"/api/chats/{EVENT_ID}/messages", json={"content": content}, headers=AUTH)
        assert res.status_code == 422
        mock_send.assert_not_called()

    @patch("app.api.v1.chat_routes.update_message")
    def test_edit_refuses_content_over_limit(self, mock_update, as_user):
        res = client.put("/api/chats/messages/7", json={"content": "a" * (CHAT_MESSAGE_MAX_LENGTH + 1)}, headers=AUTH)
        assert res.status_code == 422
        mock_update.assert_not_called()

    @patch("app.api.v1.chat_routes.send_message")
    def test_send_passes_valid_message(self, mock_send, as_user):
        # Same envelope the frontend sends.
        content = '{"v":1,"type":"text","text":"See you at 6!\\nBring snacks 🎉"}'
        mock_send.return_value = {
            "id": 1, "event_id": EVENT_ID, "sender_id": "u1", "content": content,
            "created_at": "2026-10-05T12:00:00Z",
        }
        res = client.post(f"/api/chats/{EVENT_ID}/messages", json={"content": content}, headers=AUTH)
        assert res.status_code == 201
        mock_send.assert_called_once_with("u1", EVENT_ID, content)


# ────────────────────────────────────────────────────────────────────────────
# Injection prevention in search
# ────────────────────────────────────────────────────────────────────────────

class TestLikePatterns:
    def test_escape_like(self):
        assert escape_like("a_b%c\\d") == "a\\_b\\%c\\\\d"

    @pytest.mark.parametrize("term, expected", [
        ("berlin", "%berlin%"),
        ("  berlin  ", "%berlin%"),
        ("%", "%\\%%"),
        ("_", "%\\_%"),
        ("a*b", "%ab%"),
        ("50%_off", "%50\\%\\_off%"),
        ("x,y.eq.1)", "%x,y.eq.1)%"),
    ])
    def test_like_contains_matches_literally(self, term, expected):
        assert like_contains(term) == expected

    @pytest.mark.parametrize("term", ["", "   ", "*", "***"])
    def test_like_contains_returns_none_when_nothing_to_search(self, term):
        assert like_contains(term) is None


def _query_chain(data=None, count=0):
    chain = MagicMock()
    for name in ("select", "eq", "neq", "gte", "gt", "lt", "ilike", "order", "range"):
        getattr(chain, name).return_value = chain
    chain.execute.return_value = MagicMock(data=data or [], count=count)
    return chain


class TestSearchQueriesEscapeInput:
    @patch("app.services.admin_service.supabase")
    def test_admin_user_search_escapes_wildcards(self, mock_sb):
        from app.services.admin_service import list_admin_users
        chain = _query_chain()
        mock_sb.table.return_value = chain
        list_admin_users(search="%", page=1, limit=10)
        chain.ilike.assert_called_once_with("username", "%\\%%")

    @patch("app.services.admin_service.supabase")
    def test_admin_user_search_star_only_is_ignored(self, mock_sb):
        from app.services.admin_service import list_admin_users
        chain = _query_chain()
        mock_sb.table.return_value = chain
        list_admin_users(search="*", page=1, limit=10)
        chain.ilike.assert_not_called()

    @patch("app.services.admin_service.supabase")
    def test_admin_event_search_escapes_wildcards(self, mock_sb):
        from app.services.admin_service import list_admin_events
        chain = _query_chain()
        mock_sb.table.return_value = chain
        list_admin_events(status_filter="all", search="a_%", page=1, limit=10)
        chain.ilike.assert_called_once_with("title", "%a\\_\\%%")

    @patch("app.services.event_service.supabase")
    def test_event_city_filter_escapes_wildcards(self, mock_sb):
        from app.services.event_service import list_events
        chain = _query_chain()
        mock_sb.table.return_value = chain
        list_events(city="%")
        chain.ilike.assert_called_once_with("location_name", "%\\%%")

    @patch("app.services.event_service.generate_embedding", return_value=[0.1, 0.2])
    @patch("app.services.event_service.supabase")
    def test_event_search_text_is_sent_as_rpc_parameter(self, mock_sb, _emb):
        from app.services.event_service import list_events
        mock_sb.rpc.return_value.execute.return_value = MagicMock(data=[])
        text = "'); DROP TABLE events; --"
        list_events(search=text)
        name, params = mock_sb.rpc.call_args.args
        assert name == "search_events"
        assert params["query_text"] == text  # a bound value, never part of SQL text


class TestSearchLengthLimits:
    @pytest.mark.parametrize("param", ["search", "city", "category"])
    def test_event_list_refuses_long_search_text(self, param):
        res = client.get(f"/api/events/?{param}=" + "a" * (SEARCH_TEXT_MAX_LENGTH + 1))
        assert res.status_code == 422

    @pytest.mark.parametrize("path", ["/api/admin/users", "/api/admin/events"])
    def test_admin_search_refuses_long_text(self, path, as_admin):
        res = client.get(f"{path}?search=" + "a" * (SEARCH_TEXT_MAX_LENGTH + 1), headers=AUTH)
        assert res.status_code == 422

    def test_profile_search_refuses_long_text(self, as_user):
        from app.core.dependencies import get_current_user
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u1")
        try:
            res = client.get("/api/profile/search?q=" + "a" * (SEARCH_TEXT_MAX_LENGTH + 1), headers=AUTH)
            assert res.status_code == 422
        finally:
            app.dependency_overrides.pop(get_current_user, None)
