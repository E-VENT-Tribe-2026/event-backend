-- =============================================================================
-- FR 12.4 Input Validation: database-level limits for free text
--
-- The FastAPI schemas already refuse text that breaks these limits
-- (app/core/input_limits.py). These CHECK constraints enforce the same rules
-- inside PostgreSQL, so text written to Supabase without going through the
-- backend (for example straight to the REST API with a user's token, which the
-- current row-level-security policies allow) is refused as well.
--
-- Keep the numbers here identical to app/core/input_limits.py.
--
-- Constraints are added NOT VALID: they apply to every new insert and update,
-- but rows that already exist are not checked, so this migration cannot fail
-- on old data. To find old rows that break the rules, run:
--   ALTER TABLE <table> VALIDATE CONSTRAINT <constraint>;
-- =============================================================================

-- Control characters other than tab, line feed and carriage return
-- (the same set the backend refuses).
--   [\x01-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]

-- ── profiles.bio ─────────────────────────────────────────────────────────────
ALTER TABLE public.profiles DROP CONSTRAINT IF EXISTS profiles_bio_length_check;
ALTER TABLE public.profiles
    ADD CONSTRAINT profiles_bio_length_check
    CHECK (bio IS NULL OR char_length(bio) <= 500) NOT VALID;

ALTER TABLE public.profiles DROP CONSTRAINT IF EXISTS profiles_bio_characters_check;
ALTER TABLE public.profiles
    ADD CONSTRAINT profiles_bio_characters_check
    CHECK (bio IS NULL OR bio !~ E'[\\x01-\\x08\\x0B\\x0C\\x0E-\\x1F\\x7F-\\x9F]') NOT VALID;

-- ── events.title ─────────────────────────────────────────────────────────────
ALTER TABLE public.events DROP CONSTRAINT IF EXISTS events_title_length_check;
ALTER TABLE public.events
    ADD CONSTRAINT events_title_length_check
    CHECK (char_length(btrim(title)) BETWEEN 3 AND 100) NOT VALID;

-- Titles are single-line: no control characters at all, including line breaks.
ALTER TABLE public.events DROP CONSTRAINT IF EXISTS events_title_characters_check;
ALTER TABLE public.events
    ADD CONSTRAINT events_title_characters_check
    CHECK (title !~ E'[\\x01-\\x1F\\x7F-\\x9F]') NOT VALID;

-- ── events.description ───────────────────────────────────────────────────────
ALTER TABLE public.events DROP CONSTRAINT IF EXISTS events_description_length_check;
ALTER TABLE public.events
    ADD CONSTRAINT events_description_length_check
    CHECK (description IS NULL OR char_length(description) <= 3000) NOT VALID;

ALTER TABLE public.events DROP CONSTRAINT IF EXISTS events_description_characters_check;
ALTER TABLE public.events
    ADD CONSTRAINT events_description_characters_check
    CHECK (description IS NULL OR description !~ E'[\\x01-\\x08\\x0B\\x0C\\x0E-\\x1F\\x7F-\\x9F]') NOT VALID;

-- ── event_chats.content ──────────────────────────────────────────────────────
-- Also covers system notifications, which the backend writes to the same column.
ALTER TABLE public.event_chats DROP CONSTRAINT IF EXISTS event_chats_content_length_check;
ALTER TABLE public.event_chats
    ADD CONSTRAINT event_chats_content_length_check
    CHECK (char_length(btrim(content)) BETWEEN 1 AND 2000) NOT VALID;

ALTER TABLE public.event_chats DROP CONSTRAINT IF EXISTS event_chats_content_characters_check;
ALTER TABLE public.event_chats
    ADD CONSTRAINT event_chats_content_characters_check
    CHECK (content !~ E'[\\x01-\\x08\\x0B\\x0C\\x0E-\\x1F\\x7F-\\x9F]') NOT VALID;