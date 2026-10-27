---
status: accepted
date: 2026-10-27
decision-makers: [Engineering Team]
---

# Consolidation and Ordering of Database Migrations for Clean Bootstrap

**ID**: `cpt-eventbackend-adr-database-migration-ordering`

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

A fresh database initialization fails during `supabase db push` because foundational tables (`profiles`, `events`, `friend_requests`, `friendships`, `event_chats`) were previously created manually or referenced by alteration and RLS migrations before their corresponding `CREATE TABLE` scripts ran (Issue #181). How should the project structure and order migrations so both clean fresh instances and existing environments remain fully supported and reproducible?

## Decision Drivers

* **Zero-Downtime / Idempotency**: Migrations must execute safely against clean developer/staging/test instances without breaking already-deployed production databases.
* **Chronological Correctness**: Supabase CLI runs scripts lexicographically by timestamp; table definitions must precede constraint alterations and RLS activations.
* **Developer Workflow**: Teammates must have clear guidelines and templates when submitting PRs with database scripts.

## Considered Options

* **Option 1: Single Squash Migration**: Delete all historical migrations and squash into a single monolithic script.
* **Option 2: Baseline Migration + Idempotent Ordering**: Introduce `20260101000000_initial_schema.sql` for foundational tables, make `20260411120000_enable_rls.sql` resilient, ensure `20261001141815_friendship_constraints.sql` guarantees `notifications.related_user_id`, and establish team PR guidelines.
* **Option 3: Manual SQL Execution Only**: Continue running DDL manually in Supabase Studio.

## Decision Outcome

Chosen option: **Option 2: Baseline Migration + Idempotent Ordering**, because it preserves the full git history of past sprints, avoids destructive changes to production databases (using `IF NOT EXISTS`), and restores complete reproducibility for new developers and automated CI environments.

### Consequences

* **Good**: Fresh databases can boot from scratch via `supabase db push` without errors.
* **Good**: Missing columns (`notifications.related_user_id`) are guaranteed to exist regardless of whether migrations run individually or sequentially.
* **Good**: Existing environments are untouched because all table creations and constraint additions use idempotent guards.
* **Bad**: Migration history contains initial base definitions alongside later modifications, requiring awareness documented in `supabase/MIGRATION_GUIDELINES.md`.

### Confirmation

Verified by:
1. Lexicographical migration order inspection (`20260101000000_initial_schema.sql` runs before `20260311_add_seed_rows.sql` and `20260411120000_enable_rls.sql`).
2. Verification of table dependencies and column availability across all migration scripts.
3. Full backend pytest test suite passing without regression.

## Pros and Cons of the Options

### Option 1: Single Squash Migration

* Good, because it simplifies the migration folder to 1 file.
* Bad, because it breaks migration tracking on live Supabase databases that have already applied past migration timestamps.
* Bad, because it erases historical context of past sprint PRs.

### Option 2: Baseline Migration + Idempotent Ordering

* Good, because existing environments simply skip `IF NOT EXISTS` statements without side effects.
* Good, because new environments create tables before seeds, RLS, and constraints.
* Good, because it completely solves Issue #181 and unblocks frontend tickets #146 and #147.

## Traceability

- **Issue**: [#181](https://github.com/E-VENT-Tribe-2026/event-backend/issues/181)
- **Guidelines**: [MIGRATION_GUIDELINES.md](../../../supabase/MIGRATION_GUIDELINES.md)
- **Task Plan**: [.agents/tasks/plan.md](../../../.agents/tasks/plan.md)
