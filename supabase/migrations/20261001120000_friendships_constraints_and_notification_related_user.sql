-- =============================================================================
-- Migration: 20261001120000_friendships_constraints_and_notification_related_user.sql
-- Description:
--   Friendship feature (Tickets #146, #147):
--   - friend_requests / friendships: NOT NULL participants, no self-links,
--     one pending request and one friendship per unordered pair, lookup indexes
--   - notifications: related_user_id (the user a notification is about),
--     used to clean up friend request notifications
--
-- Deployment:
--   MUST be applied to the Supabase database BEFORE deploying the friendships
--   code: the code writes notifications.related_user_id and relies on the
--   unique indexes below to map duplicate requests/friendships to HTTP 409.
--   Idempotent and safe to re-run.
--
-- Preconditions (these tables are NOT created by any migration in this repo
-- and must already exist in the live database):
--   friend_requests(id bigint, initiator_id uuid, receiver_id uuid,
--                   status varchar default 'pending', created_at)
--   friendships(id bigint, user_id uuid, friend_id uuid,
--               status varchar default 'active', origin uuid,
--               created_at, updated_at)
--   They must contain no NULL ids, no self-pairs, no duplicate pending pairs
--   and no duplicate friendships in either direction (both tables were empty
--   on 2026-10-01).
--
-- Rollback (run manually if the migration must be undone):
--   drop index if exists public.notifications_user_type_related_idx;
--   alter table public.notifications drop column if exists related_user_id;
--   drop index if exists public.friendships_friend_id_idx;
--   drop index if exists public.friendships_one_per_pair;
--   alter table public.friendships drop constraint if exists friendships_not_self;
--   drop index if exists public.friend_requests_initiator_pending_idx;
--   drop index if exists public.friend_requests_receiver_pending_idx;
--   drop index if exists public.friend_requests_one_pending_per_pair;
--   alter table public.friend_requests drop constraint if exists friend_requests_not_self;
--   (NOT NULL on the id columns is intentionally left in place.)
-- =============================================================================

-- 1. friend_requests
alter table public.friend_requests
  alter column initiator_id set not null,
  alter column receiver_id  set not null;

do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'friend_requests_not_self') then
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
  if not exists (select 1 from pg_constraint where conname = 'friendships_not_self') then
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
