-- =============================================================================
-- Migration: 20261027140000_reports_lookup_indexes.sql
-- Ticket #235: Administrators review reports (report history and closed count)
--
-- Indexes for the lookups on public.reports added by #235:
--   - reports_reporter_created_idx: "reports made" in a user's details (by
--     reporter_id, newest first); also serves the on delete set null scan of the
--     reporter_id foreign key when a profile is deleted.
--   - reports_reported_user_idx: "reports about" a user in a user's details (by
--     reported_user_id); also serves the on delete set null scan of the
--     reported_user_id foreign key.
--   - reports_event_idx: event reports about the events a user organizes in a
--     user's details (by event_id); also serves the on delete set null scan of the
--     event_id foreign key when an event is deleted. It is not limited to event reports:
--     message reports carry an event_id too, and the foreign-key scan has to find them.
--   - reports_closed_by_idx: the closed-reports count on the administrator's
--     account screen (by closed_by), and the foreign-key check on closed_by.
-- All four are partial, so they skip rows where the column is null.
--
-- Deployment: apply in the Supabase SQL editor; it needs
-- 20261027120000_report_closure_columns.sql applied first because of the closed_by column.
-- Idempotent and safe to re-run.
--
-- Rollback (run manually):
--   drop index if exists public.reports_closed_by_idx;
--   drop index if exists public.reports_event_idx;
--   drop index if exists public.reports_reported_user_idx;
--   drop index if exists public.reports_reporter_created_idx;
-- =============================================================================

create index if not exists reports_reporter_created_idx
  on public.reports (reporter_id, created_at desc)
  where reporter_id is not null;

create index if not exists reports_reported_user_idx
  on public.reports (reported_user_id)
  where reported_user_id is not null;

create index if not exists reports_event_idx
  on public.reports (event_id)
  where event_id is not null;

create index if not exists reports_closed_by_idx
  on public.reports (closed_by)
  where closed_by is not null;
