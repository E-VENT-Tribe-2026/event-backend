-- =============================================================================
-- Migration: 20261015120000_user_blocks.sql
-- Ticket #184: Block users
--
--   - user_blocks: one row per (blocker, blocked). Only the backend (service
--     role) reads and writes it: RLS is on and there are no policies.
--   - Referenced by the invitations code (#186) as user_blocks(blocker_id, blocked_id).
--
-- Deployment: apply in the Supabase SQL editor BEFORE deploying the #184 code.
-- Idempotent and safe to re-run.
--
-- Rollback (run manually):
--   drop table if exists public.user_blocks;
-- =============================================================================

create table if not exists public.user_blocks (
  blocker_id  uuid not null references public.profiles(id) on delete cascade,
  blocked_id  uuid not null references public.profiles(id) on delete cascade,
  created_at  timestamptz not null default now(),
  primary key (blocker_id, blocked_id),
  constraint user_blocks_not_self check (blocker_id <> blocked_id)
);

-- "Who has blocked me" lookups, and the blocker's list (newest first).
create index if not exists user_blocks_blocked_idx
  on public.user_blocks (blocked_id);

create index if not exists user_blocks_blocker_created_idx
  on public.user_blocks (blocker_id, created_at desc, blocked_id desc);

alter table public.user_blocks enable row level security;
