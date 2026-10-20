-- Migration: 20261021120000_admin_separation_and_cancellation_reason.sql
-- Description: Adds admin_since to profiles and cancellation_reason to events.

-- 1. Add admin_since to profiles to record when a user account was transitioned to an administrator
ALTER TABLE public.profiles
ADD COLUMN IF NOT EXISTS admin_since TIMESTAMP WITH TIME ZONE DEFAULT NULL;

-- 2. Add cancellation_reason to events to record why an event was cancelled
ALTER TABLE public.events
ADD COLUMN IF NOT EXISTS cancellation_reason TEXT DEFAULT NULL;

-- Optional index on admin_since if queried frequently
CREATE INDEX IF NOT EXISTS idx_profiles_admin_since ON public.profiles(admin_since) WHERE role = 'administrator';
