-- ====================================================================
-- Migration: Align profiles.role with the backend's 'administrator' value
-- The backend writes and checks role = 'administrator', but
-- 20261001140939_role_updates.sql only allowed 'user' and 'admin'.
-- ====================================================================

-- 1. Drop the old constraint so existing rows can be converted
ALTER TABLE profiles
    DROP CONSTRAINT IF EXISTS profiles_role_check;

-- 2. Convert legacy 'admin' values and any invalid/null values
UPDATE profiles
SET role = 'administrator'
WHERE role = 'admin';

UPDATE profiles
SET role = 'user'
WHERE role IS NULL OR role NOT IN ('user', 'administrator');

-- 3. Allow only 'user' and 'administrator'; keep the default as 'user'
ALTER TABLE profiles
    ADD CONSTRAINT profiles_role_check CHECK (role IN ('user', 'administrator'));

ALTER TABLE profiles
    ALTER COLUMN role SET DEFAULT 'user';
