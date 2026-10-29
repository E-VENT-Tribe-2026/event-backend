-- =============================================================================
-- Migration: 20261027120000_block_friend_request_race.sql
-- Ticket #227: concurrent block + friend request could leave a pending request
-- between blocked users.
--
-- The Python code checked user_blocks, then inserted the request in a separate
-- call, and blocking did not take the per-pair lock. So a block could finish
-- its cleanup between the check and the insert.
--
-- Fix: both sides now run under the same per-pair lock (lock_friend_pair):
--   1. friend_requests trigger: after taking the lock, also refuses a pending
--      request when either user has blocked the other (raises 'users_blocked').
--   2. new user_blocks trigger: after taking the lock, deletes the friendship
--      and every pending request between the two users (notifications linked
--      to a request are removed by their ON DELETE CASCADE).
-- Whichever side gets the lock first, the end state is: block exists, no
-- pending request.
--
-- Depends on: 20261015120000_user_blocks.sql, 20261022120000_fix_friend_request_send_lock.sql
-- Idempotent and safe to re-run.
--
-- Rollback (run manually):
--   drop trigger if exists user_blocks_remove_relationship on public.user_blocks;
--   drop function if exists public.remove_relationship_on_block();
--   then re-run 20261022210000_friend_request_send_lock_best_effort.sql
-- =============================================================================

-- 1. Refuse pending requests between blocked users (and between friends, as before).
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
      when others then
        null;  -- best effort, kept from 20261022210000 so a lock problem cannot break every send
    end;

    -- New statements after the lock: they see a block or friendship committed while we waited.
    if exists (
      select 1 from public.user_blocks b
      where (b.blocker_id = new.initiator_id and b.blocked_id = new.receiver_id)
         or (b.blocker_id = new.receiver_id and b.blocked_id = new.initiator_id)
    ) then
      raise exception using
        errcode = 'P0001',
        message = 'users_blocked',
        detail  = 'A pending friend request cannot exist between users where one has blocked the other.';
    end if;

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

-- 2. Blocking removes the friendship and pending requests in the same transaction.
create or replace function public.remove_relationship_on_block()
returns trigger
language plpgsql
security definer
set search_path = public, pg_catalog
as $$
begin
  begin
    perform public.lock_friend_pair(new.blocker_id, new.blocked_id);
  exception
    when others then
      null;
  end;

  delete from public.friend_requests r
  where r.status = 'pending'
    and ((r.initiator_id = new.blocker_id and r.receiver_id = new.blocked_id)
      or (r.initiator_id = new.blocked_id and r.receiver_id = new.blocker_id));

  delete from public.friendships f
  where (f.user_id = new.blocker_id and f.friend_id = new.blocked_id)
     or (f.user_id = new.blocked_id and f.friend_id = new.blocker_id);

  return new;
end;
$$;

-- INSERT and UPDATE: the backend writes blocks with an upsert, which becomes an
-- UPDATE when the block already exists.
drop trigger if exists user_blocks_remove_relationship on public.user_blocks;
create trigger user_blocks_remove_relationship
  after insert or update on public.user_blocks
  for each row execute function public.remove_relationship_on_block();