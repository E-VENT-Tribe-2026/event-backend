-- ====================================================================
-- Migration: Store and Protect Administrator Role
-- Issue: #149
-- ====================================================================

-- 1. Ensure `role` column exists on profiles with default 'user'
ALTER TABLE profiles 
    ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'user';

-- 2. Backfill existing profiles to 'user' if null or invalid
UPDATE profiles 
SET role = 'user' 
WHERE role IS NULL OR role NOT IN ('user', 'admin');

-- 3. Add CHECK constraint to enforce only 'user' or 'admin'
ALTER TABLE profiles 
    DROP CONSTRAINT IF EXISTS profiles_role_check;

ALTER TABLE profiles 
    ADD CONSTRAINT profiles_role_check CHECK (role IN ('user', 'admin'));

-- 4. Replace the overly permissive profile policy from 20260411120000_enable_rls.sql
DROP POLICY IF EXISTS "Auth all access for profiles" ON profiles;

-- Users can insert their own profile on signup
CREATE POLICY "Users can insert own profile" 
ON profiles FOR INSERT TO authenticated 
WITH CHECK (auth.uid() = id);

-- Users can update only their own profile
CREATE POLICY "Users can update own profile" 
ON profiles FOR UPDATE TO authenticated 
USING (auth.uid() = id) 
WITH CHECK (auth.uid() = id);

-- 5. Trigger function to prevent authenticated users from modifying `role` directly
CREATE OR REPLACE FUNCTION protect_profile_role()
RETURNS TRIGGER AS $$
BEGIN
    -- Check if request comes from a regular authenticated client session
    IF auth.role() = 'authenticated' THEN
        -- On UPDATE: block direct changes to the role field
        IF TG_OP = 'UPDATE' AND NEW.role IS DISTINCT FROM OLD.role THEN
            RAISE EXCEPTION 'Changing user roles directly is not permitted.';
        END IF;

        -- On INSERT: enforce default 'user' role
        IF TG_OP = 'INSERT' AND NEW.role IS DISTINCT FROM 'user' THEN
            NEW.role := 'user';
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 6. Attach trigger to profiles table
DROP TRIGGER IF EXISTS tr_protect_profile_role ON profiles;

CREATE TRIGGER tr_protect_profile_role
BEFORE INSERT OR UPDATE ON profiles
FOR EACH ROW
EXECUTE FUNCTION protect_profile_role();
