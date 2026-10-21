-- Migration: 20261021180000_account_suspension.sql
-- Issue: #192 Suspending Accounts and the Effects of Suspension
--
-- profiles.suspended_at already exists (#191): the account is suspended while it is not null,
-- and its value is the date the suspension started.
-- This adds the reason shown to the user when they try to sign in.
-- The reasons for suspending and lifting are also recorded in the audit log (logs).
--
-- Rollback:
--   alter table public.profiles drop column if exists suspension_reason;

alter table public.profiles
  add column if not exists suspended_at timestamptz,
  add column if not exists suspension_reason text;

-- Search and friend suggestions only look at accounts that are not suspended.
create index if not exists profiles_not_suspended_idx
  on public.profiles (id)
  where suspended_at is null;