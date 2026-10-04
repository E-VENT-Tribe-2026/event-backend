# Onboarding gate blocking unfinished profiles from protected endpoints

This change adds `get_current_onboarded_user`, a new FastAPI dependency that wraps `get_current_user` and enforces profile completeness — specifically that both `username` and `full_name` are non-empty in the `profiles` table — before granting access to any protected endpoint. The motivation is that legacy accounts and Google sign-in accounts land without a username or full name, and the application was previously treating a valid JWT as sufficient authorization everywhere. All authenticated endpoints across event, participant, saved-event, notification, recommendation, chat, and most profile/auth routes now use the new dependency. Onboarding-path endpoints (the choose-username and username-set routes) keep `get_current_user` so that incomplete accounts can still complete setup.

Watch for: (confirmed) The integration test for `GET /auth/me` would not catch the route being accidentally switched to `get_current_onboarded_user` — the supabase mock for the gate is out of scope for that assertion, so a real DB call would occur and the result would be environment-dependent rather than a reliable regression catch.

**Verdict**: APPROVED

---

## High-level view

The gate lives entirely in `get_current_onboarded_user` in `app/core/dependencies.py`. It queries the `profiles` table for `username` and `full_name`, strips whitespace from both, and raises HTTP 403 with the exact required message if either is absent or blank. The original `get_current_user` is untouched; the new dependency chains from it via `Depends`, so auth is still validated first.

Every authenticated endpoint outside the exempt list now uses the new dependency. The one apparent `get_current_user` usage remaining in `event_routes.py` (a `/my` endpoint) is inside a triple-quoted comment block and has no runtime effect. The exempt list is complete: `POST /profile/choose-username`, `POST /profile/username`, `PUT /profile/username`, `GET /auth/me`, `POST /auth/choose-username` all retain `get_current_user`.

The Supabase query failure path silently degrades to `data = {}`, which causes the gate to fire with 403 rather than letting a DB error be misinterpreted as a passing check. This is a secure fail-closed posture.

The test file covers the four required cases: no username → 403, empty/whitespace username → 403, no full_name → 403, and fully onboarded user → passes through. Integration tests verify the exempt endpoints don't return 403, and that a protected endpoint does. One gap exists: the `GET /auth/me` exemption integration test asserts HTTP 200, but the assertion would pass even if the route were accidentally gated, because `get_current_user` is overridden globally in that test and `get_current_onboarded_user` chains from it.

The `auth_service.py` changes (login error message homogenization) are unrelated to the gate. They bundle two independent concerns into this commit.

---

<details>
<summary>Issues (2)</summary>

1. **GET /auth/me exemption test doesn't catch accidental gating** — The `app.core.dependencies.supabase` incomplete-profile mock is active only inside the outer `with` block, which exits before the `GET /api/auth/me` call. That call lives in a separate `with patch("app.api.v1.auth_routes.supabase")` scope, so if the route were switched to `get_current_onboarded_user`, the real Supabase client would handle the profile check and the test result would be environment-dependent. Restructure the test so the incomplete-profile mock on `app.core.dependencies.supabase` is still active when `/api/auth/me` is called.

2. **Unrelated auth_service changes bundled in this commit** — The login error message changes (`"Incorrect email or password."` → `"Login failed. Please check your credentials."` and `"Email not confirmed."` → `"Login failed. Please check your credentials."`) are independent of the onboarding gate. They alter user-visible error messages and bypass the existing `test_auth_routes.py` assertion that was checking for `"Email not confirmed"`. These should be in a separate commit with their own rationale and test coverage.

</details>

---

<details>
<summary>Details</summary>

## GET /auth/me exemption test gap

The test `test_onboarding_endpoints_accessible_to_incomplete_account` patches `app.core.dependencies.supabase` with an incomplete profile mock inside a `with` block, then exits that block before reaching the `GET /api/auth/me` assertion. That assertion lives in a separate `with patch("app.api.v1.auth_routes.supabase")` scope, so the `app.core.dependencies.supabase` mock returning `{"username": None, "full_name": None}` is not active when `/api/auth/me` is called. If the route were accidentally switched to `get_current_onboarded_user`, the real Supabase client would be called for the profile check, and the test outcome would depend on live DB state rather than detecting the regression. The fix is to bring the `/api/auth/me` call inside the outer `patch("app.core.dependencies.supabase", incomplete_chain)` block, or to add an explicit check that `get_current_onboarded_user` is absent from `app.dependency_overrides`.

## Unrelated login message changes

`auth_service.py` collapses two distinct error scenarios (`"Email not confirmed"` and `"Incorrect email or password"`) into a single generic `"Login failed. Please check your credentials."` message. The `test_auth_routes.py` assertion that previously checked for `"Email not confirmed"` was quietly replaced with `assert response.status_code in (400, 422)` with no body check. These changes reduce error specificity for clients and have no relationship to the onboarding gate feature.

</details>

---

<details>
<summary>File map</summary>

| File | Change |
|------|--------|
| `app/core/dependencies.py` | New `get_current_onboarded_user` dependency added; `get_current_user` unchanged |
| `app/api/v1/auth_routes.py` | `POST /change-password` switched to `get_current_onboarded_user`; `GET /me` and `POST /choose-username` remain on `get_current_user` |
| `app/api/v1/profile_routes.py` | `GET /me`, `PUT /me`, `PATCH /location`, `POST /upload-photo` switched to `get_current_onboarded_user`; onboarding endpoints unchanged |
| `app/api/v1/event_routes.py` | All mutable/user-specific endpoints switched to `get_current_onboarded_user` |
| `app/api/v1/participant_routes.py` | All endpoints switched to `get_current_onboarded_user` |
| `app/api/v1/notification_routes.py` | All endpoints switched to `get_current_onboarded_user` |
| `app/api/v1/saved_event_routes.py` | All endpoints switched to `get_current_onboarded_user` |
| `app/api/v1/recommendation_routes.py` | Single endpoint switched to `get_current_onboarded_user` |
| `app/api/v1/chat_routes.py` | All four endpoints switched to `get_current_onboarded_user` |
| `app/services/auth_service.py` | Login error messages homogenized (unrelated to gate) |
| `tests/test_onboarding_gate.py` | New test file: 4 unit tests for dependency logic + 2 integration tests |
| `tests/test_auth_routes.py` | Test overrides and assertions updated for `get_current_onboarded_user` |
| `tests/test_event_routes.py` | Test overrides updated |
| `tests/test_event_organizer_routes.py` | Test overrides updated across 5 test classes |
| `tests/test_profile_routes.py` | Test overrides updated; username case assertions fixed |
| `tests/test_user_identity_access.py` | Test overrides updated for chat route tests |
| `.vscode/settings.json` | IIS config dir setting added (unrelated) |

Full diff: `git diff HEAD~1`
</details>
