-- =============================================================================
-- Migration: 20261119120000_protect_event_check_in_secrets.sql
-- Issue #265
--
-- Keep public event rows readable while preventing direct PostgREST access to
-- the organizer-only check-in code and QR payload on public.events.
--
-- RLS remains unchanged: its permissive event policies govern row visibility,
-- while PostgreSQL column privileges govern which fields can be selected.
-- =============================================================================

-- Remove every direct grant path on the existing table for the two API roles.
-- CASCADE also removes grants that depend on a revoked grant option held by one
-- of these roles; that is intentional because such a dependent grant could
-- preserve the check-in-secret exposure. No non-SELECT table privileges change.
revoke select on table public.events from public, anon, authenticated cascade;
revoke select (check_in_code, check_in_qr_content)
  on table public.events from public, anon, authenticated cascade;

-- Restore direct-client access to the current event fields that were already
-- publicly readable. Keep organizer-only secrets and the internal embedding out
-- of this allowlist. service_role retains its backend SELECT path below.
grant select (
  id,
  title,
  description,
  category,
  cost,
  max_capacity,
  status,
  start_datetime,
  end_datetime,
  location_name,
  latitude,
  longitude,
  created_by,
  qr_link,
  privacy,
  created_at,
  updated_at,
  cancellation_reason,
  banner_url,
  removed_at,
  removed_by
) on table public.events to anon, authenticated;

-- The backend's shared Supabase client uses service_role and selects both
-- check-in fields for organizer authorization and participant check-in.
grant select on table public.events to service_role;

-- Role membership is deployment-specific. Do not revoke from unknown parent
-- roles because they may be shared elsewhere; instead fail atomically if any
-- inherited or otherwise effective privilege can still expose either secret.
do $$
declare
  api_role name;
begin
  foreach api_role in array array['anon', 'authenticated']::name[] loop
    if has_table_privilege(api_role, 'public.events', 'select') then
      raise exception
        'Issue #265: role % still has effective table-level SELECT on public.events',
        api_role
        using errcode = '42501',
              hint = 'Inspect PUBLIC ACLs and pg_auth_members; revoke the inherited SELECT path before retrying.';
    end if;

    if has_column_privilege(api_role, 'public.events', 'check_in_code', 'select')
       or has_column_privilege(api_role, 'public.events', 'check_in_qr_content', 'select') then
      raise exception
        'Issue #265: role % still has effective SELECT on an events check-in secret',
        api_role
        using errcode = '42501',
              hint = 'Inspect PUBLIC ACLs and pg_auth_members; revoke the inherited secret-column path before retrying.';
    end if;
  end loop;
end
$$;

-- Default privileges are deliberately unchanged. They affect future objects,
-- and the verified postgres/supabase_admin defaults require an owner- and
-- platform-specific review before they can be changed safely.

-- =============================================================================
-- Rollback (emergency only): restore only the previous broad SELECT grants if
-- the security boundary must be deliberately reopened. Do not run automatically.
--
-- revoke select (id, title, description, category, cost, max_capacity, status,
--   start_datetime, end_datetime, location_name, latitude, longitude, created_by,
--   qr_link, privacy, created_at, updated_at, cancellation_reason, banner_url,
--   removed_at, removed_by) on table public.events from anon, authenticated;
-- grant select on table public.events to public, anon, authenticated;
-- =============================================================================
