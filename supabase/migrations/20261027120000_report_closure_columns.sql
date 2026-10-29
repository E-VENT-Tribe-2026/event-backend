-- =============================================================================
-- Migration: 20261027120000_report_closure_columns.sql
-- Ticket #235: Administrators review reports (admin Reports tab backend)
--
--   - reports gets outcome / closed_by / closed_at, recording how a report was
--     closed (dismissed, warned, content_removed, suspended), by whom and when.
--   - closed_by deliberately has NO "on delete set null" (unlike warnings.admin_id /
--     removed_by): a closed report must keep closed_by not null (closure check below),
--     so nulling it on account deletion would make that delete fail anyway. With the
--     default (no action) deleting an administrator who closed reports is rejected
--     with a clear foreign-key error, which also protects the audit trail.
--   - The existing status check (open / dismissed / action_taken) is not touched.
--   - Closure consistency: an open report has no closure data; a closed one has all of it.
--     The constraint is added NOT VALID: it is enforced for every insert and update;
--     NOT VALID only skips the initial scan of existing rows. A row that is already
--     closed but has no closure data fails the check on ANY later update of that row,
--     including the updates Postgres issues for ON DELETE SET NULL when the reporter
--     profile, the reported profile or the event referenced by that row is deleted.
--     Outcomes and closers are never invented.
--
-- Before deploying, run this query:
--       select id from public.reports where status <> 'open';
--   If it returns rows, reopen them or backfill outcome, closed_by and closed_at with
--   an agreed closer and outcome before applying this migration (never invent a closer
--   or outcome). If it returns nothing, no action is needed.
--
-- Follow-up: once any such rows are resolved, run:
--       alter table public.reports validate constraint reports_closure_consistent;
--
-- Deployment: apply in the Supabase SQL editor BEFORE deploying the #235 code.
-- Idempotent and safe to re-run.
--
-- Rollback (run manually):
--   alter table public.reports drop constraint if exists reports_closure_consistent;
--   alter table public.reports drop constraint if exists reports_outcome_check;
--   alter table public.reports
--     drop column if exists closed_at,
--     drop column if exists closed_by,
--     drop column if exists outcome;
-- =============================================================================

alter table public.reports
  add column if not exists outcome text,
  add column if not exists closed_by uuid references public.profiles(id),
  add column if not exists closed_at timestamptz;

alter table public.reports drop constraint if exists reports_outcome_check;
alter table public.reports
  add constraint reports_outcome_check
  check (outcome is null or outcome in ('dismissed', 'warned', 'content_removed', 'suspended'));

alter table public.reports drop constraint if exists reports_closure_consistent;
alter table public.reports
  add constraint reports_closure_consistent
  check (
    (status = 'open' and outcome is null and closed_by is null and closed_at is null)
    or
    (status <> 'open' and outcome is not null and closed_by is not null and closed_at is not null)
  ) not valid;
