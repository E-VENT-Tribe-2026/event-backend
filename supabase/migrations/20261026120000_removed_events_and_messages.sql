-- =============================================================================
-- Migration: 20261026120000_removed_events_and_messages.sql
-- Ticket #236: Administrators remove events and chat messages
--
--   - events and event_chats get removed_at / removed_by. Removing marks the row;
--     nothing is ever deleted. A row is removed while removed_at is not null.
--     removed_by is the administrator; it is set to null if that account is deleted.
--   - Only the backend sets these columns: a trigger (end of this file) rejects changes made
--     by signed-in users going straight through Supabase.
--
-- Deployment: apply in the Supabase SQL editor BEFORE deploying the #236 code.
-- Idempotent and safe to re-run.
--
-- Rollback (run manually):
--   alter table public.events      drop column if exists removed_at, drop column if exists removed_by;
--   alter table public.event_chats drop column if exists removed_at, drop column if exists removed_by;
-- =============================================================================

alter table public.events
  add column if not exists removed_at timestamptz,
  add column if not exists removed_by uuid references public.profiles(id) on delete set null;

alter table public.event_chats
  add column if not exists removed_at timestamptz,
  add column if not exists removed_by uuid references public.profiles(id) on delete set null;

-- An administrator is recorded whenever something is removed.
alter table public.events drop constraint if exists events_removed_by_needs_removed_at;
alter table public.events
  add constraint events_removed_by_needs_removed_at
  check (removed_by is null or removed_at is not null);

alter table public.event_chats drop constraint if exists event_chats_removed_by_needs_removed_at;
alter table public.event_chats
  add constraint event_chats_removed_by_needs_removed_at
  check (removed_by is null or removed_at is not null);

-- Listing removed items (admin panel) without scanning every row.
create index if not exists events_removed_at_idx
  on public.events (removed_at) where removed_at is not null;

create index if not exists event_chats_removed_at_idx
  on public.event_chats (event_id, removed_at) where removed_at is not null;

-- "Your content was removed" and "event removed" notifications use the existing
-- notifications.type text column and notifications.warning_id (see 20261021160000).

-- =============================================================================
-- Only the backend may set removed_at / removed_by.
-- events and event_chats are still readable and writable by signed-in users straight
-- through Supabase (policies in 20260411120000_enable_rls.sql). Without this trigger a
-- user could clear removed_at to undo an administrator's removal, or set it on someone
-- else's content. A column-level REVOKE would not help: the table-level UPDATE grant
-- covers every column. The backend connects as service_role and the SQL editor as
-- postgres, for which auth.role() is not 'anon' or 'authenticated'.
-- =============================================================================
create or replace function public.protect_removal_columns()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  if auth.role() in ('anon', 'authenticated') then
    if tg_op = 'INSERT' then
      if new.removed_at is not null or new.removed_by is not null then
        raise exception 'removed_at and removed_by can only be set by the backend' using errcode = '42501';
      end if;
    elsif new.removed_at is distinct from old.removed_at
       or new.removed_by is distinct from old.removed_by then
      raise exception 'removed_at and removed_by can only be changed by the backend' using errcode = '42501';
    end if;
  end if;
  return new;
end;
$$;

drop trigger if exists events_protect_removal on public.events;
create trigger events_protect_removal
  before insert or update on public.events
  for each row execute function public.protect_removal_columns();

drop trigger if exists event_chats_protect_removal on public.event_chats;
create trigger event_chats_protect_removal
  before insert or update on public.event_chats
  for each row execute function public.protect_removal_columns();

-- Rollback addition:
--   drop trigger if exists events_protect_removal on public.events;
--   drop trigger if exists event_chats_protect_removal on public.event_chats;
--   drop function if exists public.protect_removal_columns();
