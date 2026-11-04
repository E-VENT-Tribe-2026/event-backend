-- =============================================================================
-- Migration: 20261104140000_report_status_resolved.sql
-- Ticket #235 follow-up: closing a report must persist a closed status.
--
--   - Status after an action is `resolved` (dismiss stays `dismissed`).
--   - Existing `action_taken` rows are backfilled to `resolved`.
--   - Recreates reports_status_check so `resolved` is allowed. `action_taken`
--     remains accepted so a mixed deploy cannot fail mid-rollout.
--
-- Deployment: apply in the Supabase SQL editor. Idempotent and safe to re-run.
--
-- Rollback (run manually):
--   update public.reports set status = 'action_taken' where status = 'resolved';
--   alter table public.reports drop constraint if exists reports_status_check;
--   alter table public.reports
--     add constraint reports_status_check
--     check (status in ('open', 'dismissed', 'action_taken'));
-- =============================================================================

alter table public.reports drop constraint if exists reports_status_check;
alter table public.reports
  add constraint reports_status_check
  check (status in ('open', 'dismissed', 'action_taken', 'resolved'));

update public.reports
  set status = 'resolved'
  where status = 'action_taken';
