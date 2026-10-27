---
status: accepted
date: 2026-10-27
decision-makers: [Engineering Team]
---

# Protection of Suspension Fields and Automatic Tracking of Administrator Dates and Cancellation Reasons

**ID**: `cpt-eventbackend-adr-suspension-protection-and-cancellation-reasons`

## Table of Contents

- [Context and Problem Statement](#context-and-problem-statement)
- [Decision Drivers](#decision-drivers)
- [Considered Options](#considered-options)
- [Decision Outcome](#decision-outcome)
  - [Consequences](#consequences)
  - [Confirmation](#confirmation)
- [Pros and Cons of the Options](#pros-and-cons-of-the-options)
- [Traceability](#traceability)

## Context and Problem Statement

The implementation for issues #189, #191, and #192 introduced `suspended_at`, `suspension_reason`, `admin_since`, and `cancellation_reason`, but left three critical gaps (Issue #232):
1. **Suspension Bypass**: Authenticated users could issue direct `UPDATE public.profiles` statements to clear their own `suspended_at` and `suspension_reason` or forge `admin_since` because the existing trigger checked only `role`.
2. **Missing `admin_since`**: Existing administrators and users promoted directly in the database remained with `admin_since = NULL`.
3. **Missing `cancellation_reason`**: Events cancelled before the migration or cancelled through the organizer API (`POST /api/events/{event_id}/cancel`) recorded `cancellation_reason = NULL`.

How should the database and backend prevent suspension bypasses and guarantee complete administrator dates and cancellation reasons?

## Decision Drivers

* **Security & Non-Bypassability**: Ordinary users must never be able to alter administrative fields (`suspended_at`, `suspension_reason`, `admin_since`) via direct database client updates.
* **Auditability & Completeness**: Every cancelled event must carry an explicit reason, distinguishing organizer cancellations from administrator promotions or account suspensions.
* **Seamless Automation**: Promoting a user to administrator directly in PostgreSQL must automatically assign `admin_since` without manual intervention or accidental resets during routine profile edits.

## Considered Options

* **Option 1: Backend-Only Checks**: Enforce checks exclusively in the FastAPI service layer.
* **Option 2: Database Triggers + Backend Defense-in-Depth**:
  - Upgrade `protect_profile_role()` to validate `suspended_at`, `suspension_reason`, and `admin_since` when `auth.role() = 'authenticated'`.
  - Automatically manage `admin_since` during role transitions and preserve it during unrelated updates.
  - Backfill existing administrators with the rollout date (`2026-10-21T12:00:00Z`).
  - Backfill previously cancelled events with `'Cancelled by organizer'`.
  - Add database trigger and backend updates in `event_service.py` to persist `'Cancelled by organizer'`.

## Decision Outcome

Chosen option: **Option 2: Database Triggers + Backend Defense-in-Depth**, because Supabase client APIs allow authenticated requests directly to PostgREST. Enforcing restrictions at the database trigger layer prevents bypass regardless of whether updates originate from the backend API or direct client queries.

### Consequences

* **Good**: Suspended accounts cannot clear their suspension or elevate their privileges.
* **Good**: Assigning `role = 'administrator'` automatically records `admin_since` and preserves it on profile updates.
* **Good**: All cancelled events have a clear, non-null `cancellation_reason`.
* **Good**: Ordinary users can still edit their own allowed profile fields (`full_name`, `bio`, `avatar_url`, `interests`, etc.) without interference.
* **Bad**: Slight trigger overhead on profile updates, which is negligible for user traffic.

### Confirmation

Verified by:
1. Scenario testing verifying that authenticated direct updates to `suspended_at`, `suspension_reason`, or `admin_since` raise exceptions.
2. Promoting users directly in the database sets `admin_since` automatically.
3. Organizer cancellation via `/api/events/{event_id}/cancel` persists `"Cancelled by organizer"`.
4. Full test suite passing with zero regressions.

## Pros and Cons of the Options

### Option 1: Backend-Only Checks

* Good: Simple to implement in Python.
* Bad: Completely ineffective against authenticated users communicating directly with Supabase via PostgREST.

### Option 2: Database Triggers + Backend Defense-in-Depth

* Good: Enforces hard database constraints at the row level.
* Good: Transparent to backend services using service role permissions.
* Good: Completely resolves all three scenarios outlined in Issue #232.

## Traceability

- **Issue**: [#232](https://github.com/E-VENT-Tribe-2026/event-backend/issues/232)
- **Related Issues**: [#189](https://github.com/E-VENT-Tribe-2026/event-backend/issues/189), [#191](https://github.com/E-VENT-Tribe-2026/event-backend/issues/191), [#192](https://github.com/E-VENT-Tribe-2026/event-backend/issues/192)
- **Migration**: [20261027120000_fix_suspension_bypass_and_cancellation_reasons.sql](../../../supabase/migrations/20261027120000_fix_suspension_bypass_and_cancellation_reasons.sql)
- **Code**: [event_service.py](../../../app/services/event_service.py)
