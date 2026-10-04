# Pydantic schema validators for username and full_name fields

Username and full_name validation was previously enforced only inside service-layer utility functions that raised `HTTPException`. This change introduces a thin `schema_validators.py` module with two helper functions that raise `ValueError`, wires them into `@field_validator` decorators on every schema that carries these fields, and upgrades the legacy `validators.py` from `re.match` to `re.fullmatch`. The onboarding gate (`get_current_onboarded_user`) added in the same diff enforces profile completeness at the auth layer and is covered by its own test file.

Watch for: (1) **possible** — the `upload-photo` endpoint raises `HTTPException(status_code=500, detail=str(e))` on unexpected exceptions, which may expose internal SDK error messages to clients. (2) **confirmed** — no boundary-value tests exist for username length 3/20 or full_name length 3/50; off-by-one errors in the `{3,20}` quantifier and the `len` checks would not be caught.

**Verdict**: APPROVED

---

## High-level view

The central fix is a new `app/utils/schema_validators.py` that owns the validation logic for both `username` and `full_name` fields. Both `auth_schema.py` and `profile_schema.py` import from it, so the rules cannot silently diverge between schemas. The error type is `ValueError` throughout, which Pydantic converts to HTTP 422.

The `re.match` → `re.fullmatch` fix in the legacy `validators.py` is present and consistent with `schema_validators.py`. Both use `re.fullmatch(r"[a-z0-9._]{3,20}", normalized)` after lowercasing, so a trailing newline causes a fullmatch failure.

`validate_full_name_value` deliberately strips leading/trailing whitespace before applying length and character checks, so `"John Doe\n"` passes and is stored stripped. This is documented in the function's docstring and tested. The username validator takes the opposite stance — whitespace causes a fullmatch failure — and the asymmetry is intentional.

All three schemas that carry `username` or `full_name` fields receive validators: `ChooseUsernameRequest` (required, unconditional), `RegisterRequest` (optional, None-guarded), and `ProfileUpdateRequest` (optional, None-guarded). No inline `BaseModel` subclass in the route files carries these fields unguarded.

<details>
<summary>Issues (2)</summary>

1. **`upload-photo` exception leakage** — `POST /profile/upload-photo` re-raises `HTTPException(status_code=500, detail=str(e))` for unexpected exceptions, potentially exposing SDK internals or file-system paths. Replace with a generic message and log the original exception server-side.

2. **Missing boundary-value tests** — no test exercises a username of exactly 3 or exactly 20 characters, nor a full_name of exactly 3 or 50 characters. The `{3,20}` quantifier and the `3 <= len(stripped) <= 50` check are both inclusive boundaries; a one-character shift in either would go undetected. Add four parameterised cases.

</details>

---

<details>
<summary>Details</summary>

### Trailing-newline rejection

Both `validators.py` and `schema_validators.py` now use `re.fullmatch(r"[a-z0-9._]{3,20}", normalized)` after lowercasing. `"john\n"` lowercases to `"john\n"` and the fullmatch fails because `\n` is not in `[a-z0-9._]`. The `test_rejects_username_with_trailing_newline` case appears in all three schema test classes (`TestChooseUsernameRequestValidator`, `TestRegisterRequestValidator`, `TestProfileUpdateRequestValidator`).

### `upload-photo` exception leakage

The new `POST /profile/upload-photo` endpoint:

```python
except Exception as e:
    raise HTTPException(status_code=500, detail=str(e))
```

`str(e)` on a Supabase storage SDK exception can include bucket names, object paths, and sometimes credential-adjacent strings from the HTTP response body. A generic `"Upload failed. Please try again."` with a server-side log is safer.

### Test coverage

`test_schema_validators.py` covers trailing-newline rejection, too-short (2 chars), too-long (21 chars), invalid characters, empty string, spaces-only, lowercase normalisation, None-passthrough for optional fields, non-None invalid rejection for optional fields, U+2019 right single quotation mark, common punctuation, and full_name newline normalise-and-store.

Not tested: username exactly 3 or 20 characters; full_name exactly 3 or 50 characters. The `{3,20}` quantifier and `3 <= len(stripped) <= 50` are inclusive; off-by-one errors on either bound go undetected. Two lines per boundary case is all it takes.

</details>

---

<details>
<summary>File map</summary>

| File | What changed |
|---|---|
| `app/utils/schema_validators.py` | New module: `validate_username_value` and `validate_full_name_value` helpers raising `ValueError` |
| `app/utils/validators.py` | `re.match` → `re.fullmatch` in `validate_username` |
| `app/schemas/auth_schema.py` | `@field_validator` decorators on `username`/`full_name` in `RegisterRequest` and `ChooseUsernameRequest` |
| `app/schemas/profile_schema.py` | `@field_validator` decorators on `username`/`full_name` in `ProfileUpdateRequest`; new `UserSummary` model; `ProfileResponse` default-None fields |
| `app/core/dependencies.py` | New `get_current_onboarded_user` dependency enforcing profile completeness |
| `app/api/v1/auth_routes.py` | `change_user_password` migrated to `get_current_onboarded_user` |
| `app/api/v1/profile_routes.py` | Multiple endpoints migrated to `get_current_onboarded_user`; new `POST /upload-photo` endpoint |
| `tests/test_schema_validators.py` | New: unit tests for all three schema classes |
| `tests/test_onboarding_gate.py` | New: unit and integration tests for `get_current_onboarded_user` |

Full diff: `git diff main`

</details>
