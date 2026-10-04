"""Tests for Pydantic field validators on username and full_name schema fields.

Each test exercises the schema directly (no HTTP client, no mocks) — invalid data
raises pydantic.ValidationError, valid data constructs without error.
"""

import pytest
from datetime import date
from pydantic import ValidationError

from app.schemas.auth_schema import ChooseUsernameRequest, RegisterRequest
from app.schemas.profile_schema import ProfileUpdateRequest


class TestChooseUsernameRequestValidator:
    def test_rejects_username_with_trailing_newline(self):
        with pytest.raises(ValidationError) as exc_info:
            ChooseUsernameRequest(username="john\n", full_name="John Doe")
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("username",) for e in errors)

    def test_rejects_username_too_short(self):
        with pytest.raises(ValidationError):
            ChooseUsernameRequest(username="ab", full_name="John Doe")

    def test_rejects_username_too_long(self):
        with pytest.raises(ValidationError):
            ChooseUsernameRequest(username="a" * 21, full_name="John Doe")

    def test_rejects_username_invalid_characters(self):
        # Space is not an allowed username character
        with pytest.raises(ValidationError):
            ChooseUsernameRequest(username="john doe", full_name="John Doe")

    def test_rejects_full_name_empty_string(self):
        with pytest.raises(ValidationError):
            ChooseUsernameRequest(username="john", full_name="")

    def test_rejects_full_name_spaces_only(self):
        with pytest.raises(ValidationError):
            ChooseUsernameRequest(username="john", full_name="   ")

    def test_accepts_valid_username_and_full_name(self):
        schema = ChooseUsernameRequest(username="john_doe", full_name="John Doe")
        assert schema.username == "john_doe"

    def test_username_normalised_to_lowercase(self):
        schema = ChooseUsernameRequest(username="JOHN", full_name="John Doe")
        assert schema.username == "john"

    def test_accepts_full_name_with_right_single_quote(self):
        # U+2019 RIGHT SINGLE QUOTATION MARK must be accepted (e.g. O\u2019Brien)
        schema = ChooseUsernameRequest(username="john", full_name="O\u2019Brien")
        assert schema.full_name == "O\u2019Brien"

    def test_accepts_full_name_with_common_punctuation(self):
        # Hyphens, apostrophes, and periods in names must be accepted
        schema = ChooseUsernameRequest(username="john", full_name="Mary-Jane O'Neill")
        assert schema.full_name == "Mary-Jane O'Neill"


class TestRegisterRequestValidator:
    def _base_payload(self, **overrides):
        payload = {
            "email": "a@b.com",
            "password": "secret",
            "username": None,
            "full_name": None,
            "dob": date(1990, 1, 1),
            "gender": "male",
            "interests": [],
        }
        payload.update(overrides)
        return payload

    def test_accepts_username_none(self):
        # None must pass through without triggering the validator
        req = RegisterRequest(**self._base_payload())
        assert req.username is None
        assert req.full_name is None

    def test_rejects_invalid_username_when_provided(self):
        with pytest.raises(ValidationError):
            RegisterRequest(**self._base_payload(username="bad username!"))

    def test_rejects_invalid_full_name_when_provided(self):
        with pytest.raises(ValidationError):
            RegisterRequest(**self._base_payload(full_name="   "))

    def test_rejects_username_with_trailing_newline(self):
        with pytest.raises(ValidationError):
            RegisterRequest(**self._base_payload(username="john\n"))

    def test_accepts_full_name_with_right_single_quote(self):
        # U+2019 RIGHT SINGLE QUOTATION MARK must be accepted
        req = RegisterRequest(**self._base_payload(full_name="O\u2019Brien"))
        assert req.full_name == "O\u2019Brien"


class TestProfileUpdateRequestValidator:
    def test_accepts_username_none(self):
        req = ProfileUpdateRequest(username=None)
        assert req.username is None

    def test_rejects_non_none_username_with_invalid_characters(self):
        with pytest.raises(ValidationError):
            ProfileUpdateRequest(username="bad username!")

    def test_accepts_full_name_none(self):
        req = ProfileUpdateRequest(full_name=None)
        assert req.full_name is None

    def test_rejects_non_none_full_name_spaces_only(self):
        with pytest.raises(ValidationError):
            ProfileUpdateRequest(full_name="   ")

    def test_accepts_full_name_with_right_single_quote(self):
        # U+2019 RIGHT SINGLE QUOTATION MARK must be accepted
        req = ProfileUpdateRequest(full_name="O\u2019Brien")
        assert req.full_name == "O\u2019Brien"

    def test_rejects_username_with_trailing_newline(self):
        with pytest.raises(ValidationError):
            ProfileUpdateRequest(username="john\n")
