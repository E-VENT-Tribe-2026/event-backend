-- =============================================================================
-- Migration: 20261022210000_friend_request_send_lock_best_effort.sql
-- Every pending friend_requests INSERT still calls lock_friend_pair(). If that
-- function is missing, unusable (hashtextextended / EXECUTE revoked), or throws,
-- send request 500s for everyone — including pairs who are not friends.
--
-- Catch lock failures and still insert. Rejecting an already-friends pair is
-- unchanged.
--
-- Idempotent and safe to re-run.
-- =============================================================================

create or replace function public.reject_request_between_friends()
returns trigger
language plpgsql
security definer
set search_path = public, pg_catalog
as $$
begin
  if new.status = 'pending' then
    begin
      perform public.lock_friend_pair(new.initiator_id, new.receiver_id);
    exception
      when undefined_function then
        null;
      when insufficient_privilege then
        null;
      when others then
        null;
    end;
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
