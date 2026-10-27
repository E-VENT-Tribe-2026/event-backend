-- =============================================================================
-- Migration: 20261001120000_friendships_constraints_and_notification_related_user.sql
-- Description:
--   Friendship feature (Tickets #146, #147, Issue #181):
--   - friend_requests / friendships: NOT NULL participants, no self-links,
--     one pending request and one friendship per unordered pair, lookup indexes
--   - notifications: related_user_id (the user a notification is about),
--     used to clean up friend request notifications
--
-- Deployment:
--   Base tables are created by 20260101000000_initial_schema.sql.
--   Idempotent and safe to re-run.
-- =============================================================================

-- 1. friend_requests
alter table public.friend_requests
  alter column initiator_id set not null,
  alter column receiver_id  set not null;

do $$ begin
  if not exists (select 1 from pg_constraint where conname in ('friend_requests_not_self', 'friend_requests_no_self')) then
    alter table public.friend_requests
      add constraint friend_requests_not_self check (initiator_id <> receiver_id);
  end if;
end $$;

create unique index if not exists friend_requests_one_pending_per_pair
  on public.friend_requests (least(initiator_id, receiver_id), greatest(initiator_id, receiver_id))
  where status = 'pending';

create index if not exists friend_requests_receiver_pending_idx
  on public.friend_requests (receiver_id) where status = 'pending';

create index if not exists friend_requests_initiator_pending_idx
  on public.friend_requests (initiator_id) where status = 'pending';

-- 2. friendships
alter table public.friendships
  alter column user_id   set not null,
  alter column friend_id set not null;

do $$ begin
  if not exists (select 1 from pg_constraint where conname in ('friendships_not_self', 'friendships_no_self')) then
    alter table public.friendships
      add constraint friendships_not_self check (user_id <> friend_id);
  end if;
end $$;

create unique index if not exists friendships_one_per_pair
  on public.friendships (least(user_id, friend_id), greatest(user_id, friend_id));

create index if not exists friendships_friend_id_idx on public.friendships (friend_id);

-- 3. notifications
alter table public.notifications
  add column if not exists related_user_id uuid null
  references public.profiles(id) on delete set null;

create index if not exists notifications_user_type_related_idx
  on public.notifications (user_id, type, related_user_id);
