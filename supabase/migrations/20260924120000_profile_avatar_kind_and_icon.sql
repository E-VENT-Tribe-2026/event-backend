-- =============================================================================
-- Migration: 20260924120000_profile_avatar_kind_and_icon.sql
-- Description:
--   Support new profile fields (Ticket #121):
--   - avatar_kind ('photo' or 'icon', default 'icon')
--   - icon_id (identifier for ready-made icon)
--   - banner_url (URL or identifier for ready-made banner)
-- =============================================================================

ALTER TABLE public.profiles
    ADD COLUMN IF NOT EXISTS avatar_kind TEXT NOT NULL DEFAULT 'icon',
    ADD COLUMN IF NOT EXISTS icon_id TEXT,
    ADD COLUMN IF NOT EXISTS banner_url TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'profiles_avatar_kind_check'
    ) THEN
        ALTER TABLE public.profiles
            ADD CONSTRAINT profiles_avatar_kind_check
            CHECK (avatar_kind = ANY (ARRAY['photo'::text, 'icon'::text]));
    END IF;
END $$;
