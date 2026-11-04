-- =============================================================================
-- Migration: 20261027120000_fix_suspension_bypass_and_cancellation_reasons.sql
-- Issue: #232 (Related: #189, #191, #192)
-- @cpt-eventbackend-adr-suspension-protection-and-cancellation-reasons
--
-- Description:
--   1. Protect profiles.suspended_at, profiles.suspension_reason, and profiles.admin_since
--      from direct modification by authenticated users (closes suspension bypass).
--   2. Automatically record profiles.admin_since when role is assigned as 'administrator'
--      and preserve it during unrelated profile updates.
--   3. Backfill admin_since for existing administrators who currently have NULL.
--   4. Backfill cancellation_reason for previously cancelled events.
--   5. Automatically default events.cancellation_reason to 'Cancelled by organizer'
--      when status becomes 'cancelled' without a specific reason provided.
-- =============================================================================

-- 1. Upgrade protect_profile_role trigger function to protect suspension & admin dates,
--    and automatically manage admin_since upon promotion/demotion.
CREATE OR REPLACE FUNCTION public.protect_profile_role()
RETURNS TRIGGER AS $$
BEGIN
    IF auth.role() = 'authenticated' THEN
        -- On UPDATE: block direct changes to the role field
        IF TG_OP = 'UPDATE' AND NEW.role IS DISTINCT FROM OLD.role THEN
            RAISE EXCEPTION 'Changing user roles directly is not permitted.';
        END IF;

        -- On UPDATE: block direct changes to suspension fields
        IF TG_OP = 'UPDATE' AND (
            NEW.suspended_at IS DISTINCT FROM OLD.suspended_at OR
            NEW.suspension_reason IS DISTINCT FROM OLD.suspension_reason
        ) THEN
            RAISE EXCEPTION 'Modifying account suspension fields directly is not permitted.';
        END IF;

        -- On UPDATE: block direct changes to administrator start date
        IF TG_OP = 'UPDATE' AND NEW.admin_since IS DISTINCT FROM OLD.admin_since THEN
            RAISE EXCEPTION 'Modifying administrator start date directly is not permitted.';
        END IF;

        -- On INSERT: enforce default 'user' role and clear protected fields
        IF TG_OP = 'INSERT' THEN
            IF NEW.role IS DISTINCT FROM 'user' THEN
                NEW.role := 'user';
            END IF;
            NEW.suspended_at := NULL;
            NEW.suspension_reason := NULL;
            NEW.admin_since := NULL;
        END IF;
    END IF;

    -- Automatic handling of admin_since when role becomes administrator
    IF NEW.role = 'administrator' THEN
        IF TG_OP = 'INSERT' THEN
            NEW.admin_since := COALESCE(NEW.admin_since, now());
        ELSIF TG_OP = 'UPDATE' THEN
            IF OLD.role IS DISTINCT FROM 'administrator' THEN
                -- Transitioned to administrator: set start date if not explicitly supplied
                NEW.admin_since := COALESCE(NEW.admin_since, now());
            ELSIF NEW.admin_since IS NULL AND OLD.admin_since IS NOT NULL THEN
                -- Preserve existing admin_since during unrelated updates
                NEW.admin_since := OLD.admin_since;
            ELSIF NEW.admin_since IS NULL THEN
                NEW.admin_since := now();
            END IF;
        END IF;
    ELSIF NEW.role IS DISTINCT FROM 'administrator' THEN
        -- If demoted from administrator, clear admin_since
        NEW.admin_since := NULL;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tr_protect_profile_role ON public.profiles;
CREATE TRIGGER tr_protect_profile_role
BEFORE INSERT OR UPDATE ON public.profiles
FOR EACH ROW
EXECUTE FUNCTION public.protect_profile_role();


-- 2. Backfill existing administrators who have admin_since IS NULL
-- Using rollout date of 20261021120000 where admin_since was introduced
UPDATE public.profiles
SET admin_since = TIMESTAMPTZ '2026-10-21 12:00:00+00'
WHERE role = 'administrator' AND admin_since IS NULL;


-- 3. Backfill previously cancelled events that have no cancellation_reason
UPDATE public.events
SET cancellation_reason = 'Cancelled by organizer'
WHERE status = 'cancelled' AND (cancellation_reason IS NULL OR btrim(cancellation_reason) = '');


-- 4. Trigger to ensure any event cancelled directly or via service gets 'Cancelled by organizer'
-- if no specific reason (such as suspension or administrator promotion) was provided.
CREATE OR REPLACE FUNCTION public.set_default_event_cancellation_reason()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status = 'cancelled' AND (OLD.status IS DISTINCT FROM 'cancelled' OR TG_OP = 'INSERT') THEN
        IF NEW.cancellation_reason IS NULL OR btrim(NEW.cancellation_reason) = '' THEN
            NEW.cancellation_reason := 'Cancelled by organizer';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tr_set_default_event_cancellation_reason ON public.events;
CREATE TRIGGER tr_set_default_event_cancellation_reason
BEFORE INSERT OR UPDATE ON public.events
FOR EACH ROW
EXECUTE FUNCTION public.set_default_event_cancellation_reason();
