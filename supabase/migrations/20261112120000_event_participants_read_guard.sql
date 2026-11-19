-- =============================================================================
-- Migration: 20261112120000_event_participants_read_guard.sql
-- Ticket #257: Participant list privacy via direct Supabase access
--
-- The participant list privacy can be bypassed through direct Supabase access
-- (related requirement: backend #187).
--
-- Purpose: the participant list of an event must only be readable by people who
-- are allowed to see it, also when a client queries public.event_participants
-- straight through Supabase (PostgREST or realtime) instead of the backend API.
--
-- Why a RESTRICTIVE policy: the baseline policies on public.event_participants
-- ("Auth read access for event_participants" and "Auth all access for
-- event_participants") are permissive and use USING (true). Permissive policies
-- are OR-ed together, and the FOR ALL policy also grants SELECT, so any signed-in
-- user can read every row. A RESTRICTIVE policy is AND-ed on top of them, so the
-- baseline policies stay untouched and the guard layers over them.
--
-- What is readable (SELECT only):
--   - the caller's own row (user_id = auth.uid());
--   - every row of an event the caller organizes (events.created_by = auth.uid());
--   - every row of an event the caller participates in;
--   - everything, for an administrator signed in with MFA (aal2 session).
--
-- Definitions:
--   - Participant: any event_participants row of the caller for that event,
--     regardless of its status. This matches can_view_participants in
--     app/services/participant_service.py.
--   - Organizer: the caller is events.created_by of the event. This is independent
--     of any participant row. A NULL created_by means the event has no organizer.
--
-- Helpers: public.is_event_organizer(uuid) and public.is_event_participant(uuid)
-- are SECURITY DEFINER with search_path pinned to the empty string (every object is
-- schema-qualified). SECURITY DEFINER is needed because a policy on
-- event_participants that queries event_participants would recurse, and because the
-- events SELECT may be restricted by other policies.
-- public.is_administrator() is redefined here identically to the
-- 20261111120000 migration, so this migration works whichever one is applied first.
-- EXECUTE on the helpers stays granted to anon and authenticated on purpose:
-- restrictive policy expressions may be evaluated for anon, and a missing grant
-- would produce a permission error instead of an empty result. The helpers only
-- describe the caller's own relationship to an event and reveal a boolean.
--
-- Realtime: INSERT and UPDATE realtime payloads are filtered by this policy, so
-- outsiders (non-participants) no longer receive other users' participant rows.
-- DELETE events are not filtered by RLS in Supabase Realtime (they may still reach
-- outsiders with minimal key columns). Homepage attendee counters that rely on
-- participant realtime INSERT events will stop updating for non-participants.
-- The participant count and friends-attending data stay available through the
-- backend endpoints /participants/count and /participants/friends (service role,
-- which bypasses RLS).
--
-- Frontend verification: the frontend main and dev branches do not use this table
-- directly (see Writes below). Before applying, still verify that no other client
-- (for example a mobile app) writes or reads event_participants directly through
-- Supabase; such a read or count would drop to the caller's visible rows only, and
-- such a write would be denied.
--
-- Writes: direct INSERT, UPDATE and DELETE on event_participants are now denied to
-- anon and authenticated by three RESTRICTIVE policies:
-- "event_participants_no_direct_insert", "event_participants_no_direct_update" and
-- "event_participants_no_direct_delete". Reason: the open baseline FOR ALL policy
-- ("Auth all access for event_participants", USING (true)) let any signed-in user
-- create their own participant row and thereby read the participant list, bypass the
-- backend join checks (blocked/hidden/cancelled, notifications), forge rows and
-- delete rows. Only the backend (service role, which has BYPASSRLS) writes
-- participants. Evidence: the backend performs all participant writes (join, leave
-- and remove endpoints) with the service role, and the frontend
-- (E-VENT-Tribe-2026/event-frontend, main and dev branches were checked) never reads
-- or writes event_participants directly: it uses Supabase for auth and realtime only,
-- and its realtime subscribes to a table named 'participants', which does not exist
-- in this schema. The baseline policies are left untouched.
--
-- Index: event_participants_event_user_idx (event_id, user_id) supports the helper
-- lookups and the per-event policy check. It is non-unique.
--
-- Pre-flight: inspect the current policies on the table first:
--   select policyname, permissive, roles, cmd, qual, with_check from pg_policies where schemaname = 'public' and tablename = 'event_participants' order by policyname;
--
-- Deployment: apply in the Supabase SQL editor. Idempotent and safe to re-run
-- (functions use CREATE OR REPLACE, the index uses IF NOT EXISTS, the policies are
-- dropped by name then recreated).
--
-- Rollback: see the commented, emergency-only section at the end of this file.
-- =============================================================================

-- True only for an administrator whose session passed MFA (aal2).
create or replace function public.is_administrator()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.profiles p
    where p.id = auth.uid() and p.role = 'administrator'
  ) and (auth.jwt() ->> 'aal') = 'aal2'
$$;

revoke all on function public.is_administrator() from public;
grant execute on function public.is_administrator() to anon, authenticated;

-- True when the caller created the event (NULL created_by never matches).
create or replace function public.is_event_organizer(uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.events e
    where e.id = $1 and e.created_by = auth.uid()
  )
$$;

revoke all on function public.is_event_organizer(uuid) from public;
grant execute on function public.is_event_organizer(uuid) to anon, authenticated;

-- True when the caller has a participant row for the event (any status).
create or replace function public.is_event_participant(uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.event_participants ep
    where ep.event_id = $1 and ep.user_id = auth.uid()
  )
$$;

revoke all on function public.is_event_participant(uuid) from public;
grant execute on function public.is_event_participant(uuid) to anon, authenticated;

create index if not exists event_participants_event_user_idx
  on public.event_participants (event_id, user_id);

drop policy if exists "event_participants_read_guard" on public.event_participants;
create policy "event_participants_read_guard" on public.event_participants
  as restrictive for select
  using (
    user_id = auth.uid()
    or public.is_event_organizer(event_id)
    or public.is_event_participant(event_id)
    or public.is_administrator()
  );

drop policy if exists "event_participants_no_direct_insert" on public.event_participants;
create policy "event_participants_no_direct_insert" on public.event_participants
  as restrictive for insert
  with check (false);

drop policy if exists "event_participants_no_direct_update" on public.event_participants;
create policy "event_participants_no_direct_update" on public.event_participants
  as restrictive for update
  using (false)
  with check (false);

drop policy if exists "event_participants_no_direct_delete" on public.event_participants;
create policy "event_participants_no_direct_delete" on public.event_participants
  as restrictive for delete
  using (false);

-- =============================================================================
-- Rollback (EMERGENCY ONLY, run manually).
-- WARNING: this reopens the hole: every signed-in user can read the participant
-- list of every event again through direct Supabase access, and can again insert,
-- update and delete participant rows directly (rolling back reopens both the read
-- hole and direct writes).
--
-- DROP POLICY IF EXISTS "event_participants_no_direct_delete" ON public.event_participants;
-- DROP POLICY IF EXISTS "event_participants_no_direct_update" ON public.event_participants;
-- DROP POLICY IF EXISTS "event_participants_no_direct_insert" ON public.event_participants;
-- DROP POLICY IF EXISTS "event_participants_read_guard" ON public.event_participants;
-- DROP INDEX IF EXISTS public.event_participants_event_user_idx;
-- DROP FUNCTION IF EXISTS public.is_event_participant(uuid);
-- DROP FUNCTION IF EXISTS public.is_event_organizer(uuid);
--
-- Note: is_administrator() is shared with the 20261111120000 migration and is
-- NOT dropped here.
--
-- Order: roll this migration back (drop event_participants_read_guard) BEFORE
-- running the 20261111120000 rollback, because that rollback drops
-- is_administrator() which this policy depends on. Never use CASCADE for it.
-- =============================================================================
