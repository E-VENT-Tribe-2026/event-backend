# Implementation Plan: Pydantic Input Validators for Username and Full-Name Fields

## Context

The `validate_username` and `validate_full_name` utilities in `app/utils/validators.py` are
called from the service layer, not at the schema boundary. This means malformed values (e.g.
`"john\n"`, empty strings, strings with illegal characters) can pass Pydantic deserialization
and enter the service layer before validation fires, producing inconsistent errors.

The fix: add `@field_validator` methods directly to the three request schemas that accept
`username` or `full_name` fields, so FastAPI rejects bad input at deserialization time with
HTTP 422 before the request body ever reaches a route handler.

### Design decisions

**`@field_validator` over `Annotated` constraints.** The existing codebase uses
`@model_validator` in `ChangePasswordRequest` — the `@field_validator` decorator is the
single-field analogue of that same Pydantic v2 style and requires no new imports beyond what
is already in use. `Annotated` with `StringConstraints` would handle the regex case but cannot
express the multi-rule `full_name` check (letter presence, character-by-character allowlist)
without a custom type, making it harder to read and maintain.

**Validator logic re-implemented inline, not delegated to `validate_username`/`validate_full_name`.**
Those utilities raise `HTTPException`, which is the wrong exception type inside a Pydantic
validator (should raise `ValueError`). Re-implementing the same logic with `ValueError` is
the correct approach; no changes to the utilities are needed.

**`re.fullmatch` instead of `re.match` for `username`.** The existing utility uses
`re.match(r"^[a-z0-9._]{3,20}$", normalized)`, which the bug report confirmed accepts a
trailing newline because `$` can match before a final `\n`. Using `re.fullmatch(r"[a-z0-9._]{3,20}", normalized)`
fixes this without changing the allowed character set.

**Optional fields skip validation when `None`.** `RegisterRequest.username`,
`RegisterRequest.full_name`, and `ProfileUpdateRequest.username` / `full_name` are all
`Optional[str] = None`. The validators must return `None` unchanged so that existing tests
that pass `username=None` and `full_name=None` keep working.

---

## Schemas requiring validators

| Schema class | File | Fields | Notes |
|---|---|---|---|
| `ChooseUsernameRequest` | `app/schemas/auth_schema.py` | `username: str`, `full_name: str` | Both required (non-optional); always validate |
| `RegisterRequest` | `app/schemas/auth_schema.py` | `username: Optional[str]`, `full_name: Optional[str]` | Skip when `None` |
| `ProfileUpdateRequest` | `app/schemas/profile_schema.py` | `username: Optional[str]`, `full_name: Optional[str]` | Skip when `None` |

No other route files reference request schemas that accept `username` or `full_name` for
user input (confirmed by scanning all files in `app/api/v1/`). The `ProfileResponse`,
`UserSummary`, and `ChatMessageResponse` classes carry these fields as output-only data
shapes and must not have input validators added.

---

## Plan

- [ ] 1. Add `@field_validator` for `username` and `full_name` to `ChooseUsernameRequest`
         and `RegisterRequest` in `app/schemas/auth_schema.py`.

  **Import change:** add `field_validator` to the existing `from pydantic import …` line.
  Also add `import re` at the top.

  **`ChooseUsernameRequest`** — both fields are required (`str`, not `Optional`), so the
  validators always fire.

  `validate_username` (mode `"before"`, field `"username"`):
  1. Strip the value with `str(v).strip()` then lowercase: `normalized = str(v).strip().lower()`.
  2. Apply `re.fullmatch(r"[a-z0-9._]{3,20}", normalized)`. If no match, raise
     `ValueError("Username must be between 3 and 20 characters and contain only lowercase letters, digits, underscores, and full stops.")`.
  3. Return `normalized`.

  `validate_full_name` (mode `"before"`, field `"full_name"`):
  1. `stripped = str(v).strip()`.
  2. If `not stripped`: raise `ValueError("Full name is required and cannot be empty or only spaces.")`.
  3. If `not (3 <= len(stripped) <= 50)`: raise `ValueError("Full name must be between 3 and 50 characters once leading and trailing spaces are removed.")`.
  4. If `not any(c.isalpha() for c in stripped)`: raise `ValueError("Full name must contain at least one letter.")`.
  5. `ALLOWED_NAME_PUNCTUATION = set(".'-,\"''()")` — iterate over `stripped`; for any char
     that is not `.isalpha()`, not `' '`, and not in the set, raise
     `ValueError("Full name must contain only letters, spaces, and common punctuation.")`.
  6. Return `stripped`.

  **`RegisterRequest`** — same two validators, but wrap the body of each in
  `if v is None: return None` at the very top so `Optional` fields pass through unmodified.

  Files: `app/schemas/auth_schema.py`

  Verify: `python -m pytest tests/test_auth_routes.py -v` — all existing tests pass.

- [ ] 2. Add `@field_validator` for `username` and `full_name` to `ProfileUpdateRequest`
         in `app/schemas/profile_schema.py`.

  **Import change:** add `field_validator` to the `from pydantic import …` line and add
  `import re` at the top.

  Both fields in `ProfileUpdateRequest` are `Optional[str] = None`, so both validators must
  begin with `if v is None: return None`.

  The validator logic for each field is identical to the `RegisterRequest` validators (same
  `re.fullmatch` for username, same multi-rule check for full_name).

  Files: `app/schemas/profile_schema.py`

  Verify: `python -m pytest tests/test_profile_routes.py -v` — all existing tests pass.

- [ ] 3. Add `tests/test_schema_validators.py` covering the six required scenarios plus
         surrounding cases.

  Use direct schema instantiation (no HTTP client, no mocks needed) — constructing a schema
  with invalid data raises `pydantic.ValidationError`; valid data constructs without error.
  This keeps the tests fast and isolated.

  **Test class `TestChooseUsernameRequestValidator`:**

  1. `test_rejects_username_with_trailing_newline` — `ChooseUsernameRequest(username="john\n", full_name="John Doe")` raises `ValidationError`. Assert the error mentions the `username` field.
  2. `test_rejects_username_too_short` — `ChooseUsernameRequest(username="ab", full_name="John Doe")` raises `ValidationError`.
  3. `test_rejects_username_too_long` — `ChooseUsernameRequest(username="a" * 21, full_name="John Doe")` raises `ValidationError`.
  4. `test_rejects_username_invalid_characters` — `ChooseUsernameRequest(username="john doe", full_name="John Doe")` raises `ValidationError` (space is not allowed).
  5. `test_rejects_full_name_empty_string` — `ChooseUsernameRequest(username="john", full_name="")` raises `ValidationError`.
  6. `test_rejects_full_name_spaces_only` — `ChooseUsernameRequest(username="john", full_name="   ")` raises `ValidationError`.
  7. `test_accepts_valid_username_and_full_name` — `ChooseUsernameRequest(username="john_doe", full_name="John Doe")` constructs without error; assert `schema.username == "john_doe"`.
  8. `test_username_normalised_to_lowercase` — `ChooseUsernameRequest(username="JOHN", full_name="John Doe")` constructs; assert `schema.username == "john"`.

  **Test class `TestRegisterRequestValidator`:**

  9. `test_accepts_username_none` — `RegisterRequest(email="a@b.com", password="x", username=None, full_name=None, dob=date(1990,1,1), gender="male", interests=[])` constructs without error.
  10. `test_rejects_invalid_username_when_provided` — same but `username="bad username!"` raises `ValidationError`.
  11. `test_rejects_invalid_full_name_when_provided` — same but `full_name="   "` raises `ValidationError`.

  **Test class `TestProfileUpdateRequestValidator`:**

  12. `test_accepts_username_none` — `ProfileUpdateRequest(username=None)` constructs without error.
  13. `test_rejects_non_none_username_with_invalid_characters` — `ProfileUpdateRequest(username="bad username!")` raises `ValidationError`.
  14. `test_accepts_full_name_none` — `ProfileUpdateRequest(full_name=None)` constructs without error.
  15. `test_rejects_non_none_full_name_spaces_only` — `ProfileUpdateRequest(full_name="   ")` raises `ValidationError`.

  Files: `tests/test_schema_validators.py`

  Verify: `python -m pytest tests/test_schema_validators.py -v` — all 15 tests pass.

- [ ] 4. Run the full test suite to confirm nothing regressed.

  Command: `python -m pytest` (run from `c:\Users\User\Desktop\event-backend`).

  Expected outcome: all previously-passing tests continue to pass and the new
  `test_schema_validators.py` tests pass. Zero failures, zero errors.
