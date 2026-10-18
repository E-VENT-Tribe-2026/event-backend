-- =============================================================================
-- Migration: 20261018120000_friend_request_accept_atomic.sql
-- Bug: accepting a friend request deleted the pending request and created the
-- friendship in two separate API calls. A new request sent in between could
-- leave two users as friends with a pending request still between them.
--
--   - lock_friend_pair(a, b): transaction-scoped advisory lock on the unordered
--     pair. Every write that can create a friendship or a pending request for a
--     pair takes it first, so those writes are serialized per pair.
--   - accept_friend_request(request_id, receiver_id): deletes the pending
--     request and creates the friendship in ONE transaction, under the pair
--     lock. Returns no row when the request is not pending for that receiver.
--   - friend_requests trigger: a pending request between users who are already
--     friends is rejected with SQLSTATE 23505, which the backend maps to
--     409 already_friends.
--   - friendships trigger: creating a friendship removes any pending request
--     between the pair, whatever code path creates it.
--   - One-off cleanup of pending requests between users who are already friends.
--
-- Deployment: apply in the Supabase SQL editor BEFORE deploying the backend
-- code that calls accept_friend_request. Idempotent and safe to re-run.
--
-- Rollback (run manually):
--   drop trigger if exists friendships_remove_pending_requests on public.friendships;
--   drop function if exists public.remove_pending_requests_on_friendship();
--   drop trigger if exists friend_requests_reject_between_friends on public.friend_requests;
--   drop function if exists public.reject_request_between_friends();
--   drop function if exists public.accept_friend_request(bigint, uuid);
--   drop function if exists public.lock_friend_pair(uuid, uuid);
-- =============================================================================

-- 1. Per-pair lock, released automatically when the transaction ends
create or replace function public.lock_friend_pair(user_a uuid, user_b uuid)
returns void
language sql
set search_path = public
as $$
  select pg_advisory_xact_lock(
    hashtextextended('friend_pair:' || least(user_a, user_b)::text || ':' || greatest(user_a, user_b)::text, 0)
  );
$$;

revoke execute on function public.lock_friend_pair(uuid, uuid) from public, anon, authenticated;
grant execute on function public.lock_friend_pair(uuid, uuid) to service_role;

-- 2. Reject a pending request between users who are already friends
create or replace function public.reject_request_between_friends()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if new.status = 'pending' then
    perform public.lock_friend_pair(new.initiator_id, new.receiver_id);
    -- New statement after the lock: sees a friendship committed while we waited.
    if exists (
      select 1 from public.friendships f
      where (f.user_id = new.initiator_id and f.friend_id = new.receiver_id)
         or (f.user_id = new.receiver_id and f.friend_id = new.initiator_id)
    ) then
      raise exception using
        errcode = 'unique_violation',
        message = 'already_friends',
        detail  = 'A pending friend request cannot exist between users who are already friends.';
    end if;
  end if;
  return new;
end;
$$;

drop trigger if exists friend_requests_reject_between_friends on public.friend_requests;
create trigger friend_requests_reject_between_friends
  before insert or update of status, initiator_id, receiver_id on public.friend_requests
  for each row execute function public.reject_request_between_friends();

-- 3. Creating a friendship removes any pending request between the pair
create or replace function public.remove_pending_requests_on_friendship()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  perform public.lock_friend_pair(new.user_id, new.friend_id);
  delete from public.friend_requests
  where status = 'pending'
    and ((initiator_id = new.user_id and receiver_id = new.friend_id)
      or (initiator_id = new.friend_id and receiver_id = new.user_id));
  return new;
end;
$$;

drop trigger if exists friendships_remove_pending_requests on public.friendships;
create trigger friendships_remove_pending_requests
  after insert on public.friendships
  for each row execute function public.remove_pending_requests_on_friendship();

-- 4. Accept a request atomically: delete it and create the friendship together
create or replace function public.accept_friend_request(p_request_id bigint, p_receiver_id uuid)
returns table (friendship_id bigint, friend_since timestamptz, created boolean)
language plpgsql
security definer
set search_path = public
as $$
declare
  v_initiator uuid;
begin
  select r.initiator_id into v_initiator
  from public.friend_requests r
  where r.id = p_request_id and r.receiver_id = p_receiver_id and r.status = 'pending';
  if not found then
    return;
  end if;

  perform public.lock_friend_pair(v_initiator, p_receiver_id);

  -- Re-check under the lock: a concurrent accept, decline or cancel may have won.
  delete from public.friend_requests r
  where r.id = p_request_id and r.receiver_id = p_receiver_id and r.status = 'pending';
  if not found then
    return;
  end if;

  return query
    insert into public.friendships (user_id, friend_id, origin, status)
    values (v_initiator, p_receiver_id, v_initiator, 'active')
    on conflict do nothing
    returning friendships.id, friendships.created_at, true;

  if not found then
    -- The pair is already friends: report the existing friendship.
    return query
      select f.id, f.created_at, false
      from public.friendships f
      where (f.user_id = v_initiator and f.friend_id = p_receiver_id)
         or (f.user_id = p_receiver_id and f.friend_id = v_initiator)
      limit 1;
  end if;
end;
$$;

-- Only the backend may call it, not signed-in users or visitors through the API.
revoke execute on function public.accept_friend_request(bigint, uuid) from public, anon, authenticated;
grant execute on function public.accept_friend_request(bigint, uuid) to service_role;

-- 5. Remove pending requests left behind by the bug
delete from public.friend_requests r
using public.friendships f
where r.status = 'pending'
  and ((f.user_id = r.initiator_id and f.friend_id = r.receiver_id)
    or (f.user_id = r.receiver_id and f.friend_id = r.initiator_id));
