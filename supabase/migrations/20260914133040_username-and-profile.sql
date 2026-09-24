-- =============================================================================
-- Migration: 20260914133040_username-and-profile.sql
-- Description:
--   1. Optional full_name (DROP NOT NULL) preserving existing account full names.
--   2. Unique usernames (case-insensitive, 3-20 chars, [a-z0-9_.], lowercase, cannot change once set).
--   3. Nullable username to allow accounts without a username until sign-in selection.
--   4. Case-insensitive unique email enforcement at database level on auth.users.
--   5. Ensure avatar_url and banner_url columns exist on profiles.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. Full Name: Make optional while preserving existing data
-- -----------------------------------------------------------------------------
ALTER TABLE public.profiles
    ALTER COLUMN full_name DROP NOT NULL;

-- -----------------------------------------------------------------------------
-- 2. Usernames: Columns, Nullability, and Constraints
-- -----------------------------------------------------------------------------
-- Ensure username column exists and is nullable (for existing accounts and Google sign-in)
ALTER TABLE public.profiles
    ADD COLUMN IF NOT EXISTS username TEXT;

ALTER TABLE public.profiles
    ALTER COLUMN username DROP NOT NULL;

-- Database-level case-insensitive unique index
DROP INDEX IF EXISTS public.profiles_username_unique_idx;
CREATE UNIQUE INDEX profiles_username_unique_idx
    ON public.profiles (LOWER(username))
    WHERE username IS NOT NULL;

-- Normalization and validation trigger for username:
-- - Converts capital letters to lowercase
-- - Validates length (3 to 20 characters) and allowed characters ([a-z0-9_.])
-- - Prevents changing username once chosen
CREATE OR REPLACE FUNCTION public.handle_profile_username()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.username IS NOT NULL THEN
        -- Normalize: convert to lowercase and trim whitespace
        NEW.username := LOWER(TRIM(NEW.username));

        -- Validate username requirements:
        -- 3 to 20 characters, lowercase letters, digits, underscores, and full stops. No spaces.
        IF NOT (NEW.username ~ '^[a-z0-9_.]{3,20}$') THEN
            RAISE EXCEPTION 'Username must be 3-20 characters long and contain only lowercase letters, digits, underscores, and full stops (no spaces).';
        END IF;
    END IF;

    -- Cannot be changed once chosen:
    -- If OLD.username was already set and is being changed to something different, reject it
    IF TG_OP = 'UPDATE' THEN
        IF OLD.username IS NOT NULL AND NEW.username IS DISTINCT FROM OLD.username THEN
            RAISE EXCEPTION 'Username cannot be changed once chosen.';
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_handle_profile_username ON public.profiles;
CREATE TRIGGER trg_handle_profile_username
    BEFORE INSERT OR UPDATE OF username ON public.profiles
    FOR EACH ROW
    EXECUTE FUNCTION public.handle_profile_username();

-- -----------------------------------------------------------------------------
-- 3. Email Uniqueness: Database-level enforcement
-- -----------------------------------------------------------------------------
-- Case-insensitive unique index on auth.users (accounts)
CREATE UNIQUE INDEX IF NOT EXISTS users_email_lower_unique_idx
    ON auth.users (LOWER(email));

-- -----------------------------------------------------------------------------
-- 4. Profile Picture & Banner: Ensure columns exist
-- -----------------------------------------------------------------------------
-- avatar_url holds either an uploaded photo URL or chosen icon URL
-- banner_url holds the chosen banner URL, if any (optional)
ALTER TABLE public.profiles
    ADD COLUMN IF NOT EXISTS avatar_url TEXT,
    ADD COLUMN IF NOT EXISTS banner_url TEXT;
