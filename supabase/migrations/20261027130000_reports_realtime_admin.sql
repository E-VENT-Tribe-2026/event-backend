-- =============================================================================
-- Migration: 20261027130000_reports_realtime_admin.sql
-- Ticket #235: Administrators review reports (admin Reports tab backend)
--
--   - reports joins the supabase_realtime publication (replica identity FULL so
--     UPDATE/DELETE payloads carry the whole row), so the admin Reports tab can
--     update live.
--   - Signed-in users get SELECT only, and RLS lets only an administrator with an
--     MFA-verified session (aal2) read rows. All writes stay with the backend
--     (service_role), as before.
--   - The profiles lookup needs no SECURITY DEFINER: profiles is readable by
--     authenticated ("Auth read access for profiles", USING true).
--
-- Deployment: apply in the Supabase SQL editor BEFORE deploying the #235 code.
-- Idempotent and safe to re-run.
--
-- Rollback (run manually):
--   do $$ begin
--     if exists (select 1 from pg_publication_tables
--                where pubname = 'supabase_realtime' and schemaname = 'public'
--                  and tablename = 'reports') then
--       alter publication supabase_realtime drop table public.reports;
--     end if;
--   end $$;
--   drop policy if exists reports_select_admin on public.reports;
--   revoke select on public.reports from authenticated;
--   alter table public.reports replica identity default;
-- =============================================================================

do $$
begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    if not exists (
      select 1 from pg_publication_tables
      where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'reports'
    ) then
      execute 'alter publication supabase_realtime add table public.reports';
    end if;
  end if;
end $$;

alter table public.reports replica identity full;

alter table public.reports enable row level security;

grant select on public.reports to authenticated;

drop policy if exists reports_select_admin on public.reports;
create policy reports_select_admin on public.reports
  for select to authenticated
  using (
    exists (
      select 1 from public.profiles p
      where p.id = auth.uid() and p.role = 'administrator'
    )
    and (auth.jwt() ->> 'aal') = 'aal2'
  );
