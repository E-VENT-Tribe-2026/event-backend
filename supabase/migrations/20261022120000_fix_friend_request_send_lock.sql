-- =============================================================================
-- Migration: 20261022120000_fix_friend_request_send_lock.sql
-- Sending a friend request started failing after the accept-race trigger was
-- added: every pending INSERT calls lock_friend_pair(), which used
-- hashtextextended() in a SQL function with search_path=public only. That
-- lookup (or EXECUTE privilege after REVOKE FROM PUBLIC) aborted the insert
-- with a 500 for pairs who were not even friends.
--
--   - Recreate lock_friend_pair as plpgsql SECURITY DEFINER using the two-int
--     advisory lock (hashtext), which exists on all supported Postgres versions.
--   - Raise already-friends with SQLSTATE 23505 so the backend maps it to 409.
--   - Grant EXECUTE to service_role (the backend insert role).
--
-- Idempotent and safe to re-run.
-- =============================================================================

create or replace function public.lock_friend_pair(user_a uuid, user_b uuid)
returns void
language plpgsql
security definer
set search_path = public, pg_catalog
as $$
begin
  if user_a is null or user_b is null then
    return;
  end if;
  perform pg_advisory_xact_lock(
    hashtext('friend_pair:' || least(user_a, user_b)::text),
    hashtext(greatest(user_a, user_b)::text)
  );
end;
$$;

revoke execute on function public.lock_friend_pair(uuid, uuid) from public, anon, authenticated;

do $$
declare
  r text;
begin
  foreach r in array array['service_role', 'postgres', 'supabase_admin']
  loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('grant execute on function public.lock_friend_pair(uuid, uuid) to %I', r);
    end if;
  end loop;
end $$;

create or replace function public.reject_request_between_friends()
returns trigger
language plpgsql
security definer
set search_path = public, pg_catalog
as $$
begin
  if new.status = 'pending' then
    perform public.lock_friend_pair(new.initiator_id, new.receiver_id);
    if exists (
      select 1 from public.friendships f
      where (f.user_id = new.initiator_id and f.friend_id = new.receiver_id)
         or (f.user_id = new.receiver_id and f.friend_id = new.initiator_id)
    ) then
      raise exception using
        errcode = '23505',
        message = 'already_friends',
        detail  = 'A pending friend request cannot exist between users who are already friends.';
    end if;
  end if;
  return new;
end;
$$;
