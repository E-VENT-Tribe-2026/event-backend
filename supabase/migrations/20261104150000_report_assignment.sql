-- =============================================================================
-- Migration: 20261104150000_report_assignment.sql
-- Ticket #235 follow-up: only the assigned administrator may act on an open report.
--
--   - reports gets assigned_to (administrator profile, or null when unassigned).
--   - ON DELETE SET NULL: deleting an administrator frees their open reports.
--   - Existing reports stay unassigned; assignment is claimed through the API.
--
-- Deployment: apply in the Supabase SQL editor. Idempotent and safe to re-run.
--
-- Rollback (run manually):
--   drop index if exists public.reports_assigned_to_idx;
--   alter table public.reports drop column if exists assigned_to;
-- =============================================================================

alter table public.reports
  add column if not exists assigned_to uuid references public.profiles(id) on delete set null;

create index if not exists reports_assigned_to_idx
  on public.reports (assigned_to)
  where assigned_to is not null;
