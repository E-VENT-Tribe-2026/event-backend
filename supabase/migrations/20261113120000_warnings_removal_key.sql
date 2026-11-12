-- =============================================================================
-- Migration: 20261113120000_warnings_removal_key.sql
-- Ticket #255: Content removal reuses an existing warning
--
-- Purpose: an administrator removal of an event or chat message always gets its
-- own warning, and a retry of the same removal reuses only that warning.
--
-- Why: give_removal_warning reused any warning for the same user and content,
-- so a removal could return an earlier manual, acknowledged or withdrawn
-- warning: no new warning, no higher count, no pending dialog.
--
-- What:
--   - warnings gets removal_key (text, nullable). Only content removals set it,
--     as 'event:<id>' or 'chat_message:<id>'. Manual warnings leave it null.
--   - A partial unique index on (user_id, removal_key) where removal_key is not
--     null guarantees at most one removal warning per user and content, and
--     makes retries race-safe.
--
-- DEPLOY ORDER: apply this migration in the Supabase SQL editor
-- BEFORE deploying the code.
-- The code assumes the column exists and has no fallback.
-- If the code is deployed first, removals that warn an owner fail with 500
-- removal_failed and are rolled back (nothing is lost; in the rare case the
-- rollback also fails, the response is removal_incomplete). Removals that give
-- no warning (an administrator owner or an event with no owner) are unaffected.
--
-- NO BACKFILL: warnings created by earlier removals keep removal_key null and
-- behave as ordinary warnings (they cannot be told apart from manual ones;
-- their content is already removed, so a retry returns 409). A withdrawn keyed
-- warning stays withdrawn on a retry, by design.
--
-- Pre-flight (read-only, run before applying):
--   select column_name, data_type from information_schema.columns
--     where table_schema = 'public' and table_name = 'warnings' order by ordinal_position;
--   select indexname, indexdef from pg_indexes
--     where schemaname = 'public' and tablename = 'warnings' order by indexname;
--
-- Deployment: idempotent and safe to re-run.
--
-- EMERGENCY-ONLY rollback (run manually). The code that uses the column must be
-- rolled back first. Dropping the column loses the removal keys.
--   -- DROP INDEX IF EXISTS public.warnings_user_removal_key_uidx;
--   -- ALTER TABLE public.warnings DROP COLUMN IF EXISTS removal_key;
-- =============================================================================

alter table public.warnings
  add column if not exists removal_key text;

create unique index if not exists warnings_user_removal_key_uidx
  on public.warnings (user_id, removal_key)
  where removal_key is not null;
