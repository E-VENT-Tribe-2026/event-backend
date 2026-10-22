-- =============================================================================
-- Migration: 20261019120000_realtime_homepage_events.sql
-- The homepage feed should pick up new, updated and cancelled events without a
-- hard reload. Supabase Realtime only broadcasts tables in supabase_realtime.
-- Replica identity FULL is required so UPDATE/DELETE payloads include the row.
--
-- Idempotent and safe to re-run.
-- =============================================================================

do $$
begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    if not exists (
      select 1 from pg_publication_tables
      where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'events'
    ) then
      execute 'alter publication supabase_realtime add table public.events';
    end if;
    if not exists (
      select 1 from pg_publication_tables
      where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'event_participants'
    ) then
      execute 'alter publication supabase_realtime add table public.event_participants';
    end if;
  end if;
end $$;

alter table public.events replica identity full;
alter table public.event_participants replica identity full;
