-- =============================================================================
-- Migration: 20261111120000_removed_content_rls_guards.sql
-- Removed events and chat messages must not be reachable straight through Supabase.
--
--   - Adds RESTRICTIVE row-level-security policies on public.events and
--     public.event_chats. Permissive policies are OR-ed together, so the existing
--     baseline policies (which let signed-in users read and write broadly) would
--     otherwise keep exposing removed rows. RESTRICTIVE policies are AND-ed on top
--     of them, so the baseline policies stay untouched and the guards layer over them.
--   - SELECT: a removed row is hidden unless the caller is an administrator
--     signed in with MFA (aal2). Chat messages of a removed event are hidden too,
--     whether or not the message itself is removed (the guards also consult the
--     parent event).
--   - UPDATE / DELETE: a removed row cannot be changed or deleted by direct access,
--     not even by an administrator. Chat messages of a removed event are locked the
--     same way, and a message cannot be moved into a removed event by UPDATE.
--     Only the backend manages removed rows.
--   - INSERT (event_chats): no new message can be added to a removed event.
--   - DELETE trigger on public.events: foreign-key cascades bypass RLS, so deleting
--     a live event would otherwise physically delete its preserved removed messages.
--     The BEFORE DELETE trigger blocks that for direct (anon/authenticated) access;
--     the backend (service role) is exempt, mirroring protect_removal_columns.
--   - Two SECURITY DEFINER policy helpers, public.is_administrator() and
--     public.event_is_removed(uuid), keep the policies from querying profiles/events
--     under the caller's own RLS (the cascade-protection trigger function is also
--     SECURITY DEFINER).
--
-- Helper hardening: all three functions pin search_path to the empty string and
-- schema-qualify every object they touch (auth.uid(), auth.jwt(), auth.role(),
-- public.profiles, public.events, public.event_chats); built-in operators and
-- functions still resolve through pg_catalog, which is always searched.
-- EXECUTE on the two policy helpers stays granted to anon and authenticated on
-- purpose: restrictive policy expressions may be evaluated for anon (anon reads
-- public.events through the baseline "Public read access" policy), and a caller
-- without EXECUTE would get a permission error instead of an empty result. The
-- helpers only reveal a boolean.
--
-- Known limitation (rare race): an INSERT into public.event_chats whose snapshot
-- predates the commit of an event removal can still land in the just-removed event,
-- because the insert guard reads the event under the inserter's snapshot. No locking
-- trigger is added; such a message is hidden and frozen by the guards afterwards.
-- The same class of snapshot race applies to the BEFORE DELETE trigger: if an
-- administrator's uncommitted removal of a message is in flight while a user deletes
-- the live event, the trigger's check can miss it and the cascade may then delete the
-- just-removed message. The window is very narrow; accepted, no locking is added.
--
-- Backend: the service role has BYPASSRLS, so these policies never apply to it.
-- Triggers still run for it; protect_removal_columns lets service_role change
-- removed_at/removed_by and protect_removed_chats_on_event_delete exempts it.
-- Interplay for signed-in users: UPDATE ... USING hides a removed row, so trying to
-- clear removed_at on it matches 0 rows (no error, nothing changes); setting
-- removed_at on a live row is rejected with 42501 by protect_removal_columns.
--
-- Realtime: because RLS hides a removed row from non-admin users, realtime does not
-- deliver removal updates to non-admin subscribers. Clients must not rely on a
-- realtime event to learn that something was removed.
--
-- Verification needed: before relying on this, check against the live database
-- that the vector-search RPCs (security definer vs invoker, and whether they
-- filter on removed_at), saved_events and notifications do not return removed
-- content. These guards only cover direct reads and writes of events/event_chats.
--
-- Pre-flight: inspect the current policies on both tables first:
--   select policyname, permissive, roles, cmd, qual, with_check
--   from pg_policies
--   where schemaname = 'public' and tablename in ('events', 'event_chats')
--   order by tablename, policyname;
--
-- Deployment: apply in the Supabase SQL editor. Idempotent and safe to re-run
-- (functions use CREATE OR REPLACE, policies are dropped by name then recreated).
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

-- True when the event exists and has been removed.
create or replace function public.event_is_removed(uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.events e
    where e.id = $1 and e.removed_at is not null
  )
$$;

revoke all on function public.event_is_removed(uuid) from public;
grant execute on function public.event_is_removed(uuid) to anon, authenticated;

-- ---------- public.events ----------

drop policy if exists "events_removed_select_guard" on public.events;
create policy "events_removed_select_guard" on public.events
  as restrictive for select
  using (removed_at is null or public.is_administrator());

drop policy if exists "events_removed_update_guard" on public.events;
create policy "events_removed_update_guard" on public.events
  as restrictive for update
  using (removed_at is null)
  with check (removed_at is null);

drop policy if exists "events_removed_delete_guard" on public.events;
create policy "events_removed_delete_guard" on public.events
  as restrictive for delete
  using (removed_at is null);

-- ---------- public.event_chats ----------

drop policy if exists "event_chats_removed_select_guard" on public.event_chats;
create policy "event_chats_removed_select_guard" on public.event_chats
  as restrictive for select
  using (
    (removed_at is null and not public.event_is_removed(event_id))
    or public.is_administrator()
  );

drop policy if exists "event_chats_removed_update_guard" on public.event_chats;
create policy "event_chats_removed_update_guard" on public.event_chats
  as restrictive for update
  using (removed_at is null and not public.event_is_removed(event_id))
  with check (removed_at is null and not public.event_is_removed(event_id));

drop policy if exists "event_chats_removed_delete_guard" on public.event_chats;
create policy "event_chats_removed_delete_guard" on public.event_chats
  as restrictive for delete
  using (removed_at is null and not public.event_is_removed(event_id));

drop policy if exists "event_chats_removed_insert_guard" on public.event_chats;
create policy "event_chats_removed_insert_guard" on public.event_chats
  as restrictive for insert
  with check (not public.event_is_removed(event_id));

-- ---------- cascade protection ----------

-- event_chats.event_id references events(id) ON DELETE CASCADE, and FK cascades
-- bypass RLS. Refuse to delete an event that still has removed (preserved)
-- messages when the caller is a direct anon/authenticated client.
create or replace function public.protect_removed_chats_on_event_delete()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if auth.role() in ('anon', 'authenticated') then
    if exists (
      select 1 from public.event_chats c
      where c.event_id = old.id and c.removed_at is not null
    ) then
      raise exception 'cannot delete an event that has removed chat messages'
        using errcode = '42501';
    end if;
  end if;
  return old;
end;
$$;

revoke all on function public.protect_removed_chats_on_event_delete() from public;

drop trigger if exists events_protect_removed_chats on public.events;
create trigger events_protect_removed_chats
  before delete on public.events
  for each row execute function public.protect_removed_chats_on_event_delete();

-- =============================================================================
-- Rollback (EMERGENCY ONLY, run manually).
-- WARNING: this reopens the access hole: removed events and messages become
-- readable and writable again through direct Supabase access.
--
-- DROP POLICY IF EXISTS "events_removed_select_guard" ON public.events;
-- DROP POLICY IF EXISTS "events_removed_update_guard" ON public.events;
-- DROP POLICY IF EXISTS "events_removed_delete_guard" ON public.events;
-- DROP POLICY IF EXISTS "event_chats_removed_select_guard" ON public.event_chats;
-- DROP POLICY IF EXISTS "event_chats_removed_update_guard" ON public.event_chats;
-- DROP POLICY IF EXISTS "event_chats_removed_delete_guard" ON public.event_chats;
-- DROP POLICY IF EXISTS "event_chats_removed_insert_guard" ON public.event_chats;
-- DROP TRIGGER IF EXISTS events_protect_removed_chats ON public.events;
-- DROP FUNCTION IF EXISTS public.protect_removed_chats_on_event_delete();
-- DROP FUNCTION IF EXISTS public.event_is_removed(uuid);
-- DROP FUNCTION IF EXISTS public.is_administrator();
-- =============================================================================
