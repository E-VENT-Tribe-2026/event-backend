-- =============================================================================
-- Migration: 20261029120000_revoke_user_sessions.sql
-- Ticket #228: making a user an administrator must end their existing sessions.
--
-- The backend called POST /auth/v1/admin/users/{id}/logout, which Supabase Auth
-- does not have, and ignored the response. Supabase Auth has no admin route to
-- sign out another user, so the backend now calls this function instead.
--
--   - revoke_user_sessions(p_user_id): deletes the user's rows in auth.sessions
--     and auth.refresh_tokens. Returns how many sessions were ended.
--       * Refresh tokens stop working at once (their rows are gone).
--       * Access tokens stop working at once too: every backend request checks
--         the token with supabase.auth.get_user(), and Supabase Auth refuses a
--         token whose session no longer exists (403 session_not_found).
--   - Only the backend (service_role) may call it.
--
-- Deployment: apply in the Supabase SQL editor BEFORE deploying the #228 code.
-- Without it, making a user an administrator returns 500 and changes nothing.
-- Idempotent and safe to re-run.
--
-- Rollback (run manually):
--   drop function if exists public.revoke_user_sessions(uuid);
-- =============================================================================

create or replace function public.revoke_user_sessions(p_user_id uuid)
returns integer
language plpgsql
security definer
set search_path = public, pg_catalog
as $$
declare
  v_count integer;
begin
  if p_user_id is null then
    return 0;
  end if;

  delete from auth.refresh_tokens where user_id = p_user_id::text;
  delete from auth.sessions where user_id = p_user_id;
  get diagnostics v_count = row_count;
  return v_count;
end;
$$;

revoke execute on function public.revoke_user_sessions(uuid) from public;

do $$
declare
  r text;
begin
  foreach r in array array['anon', 'authenticated']
  loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('revoke execute on function public.revoke_user_sessions(uuid) from %I', r);
    end if;
  end loop;
  foreach r in array array['service_role', 'postgres', 'supabase_admin']
  loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('grant execute on function public.revoke_user_sessions(uuid) to %I', r);
    end if;
  end loop;
end $$;