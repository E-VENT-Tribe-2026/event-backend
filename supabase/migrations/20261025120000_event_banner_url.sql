-- Event photo banners are stored in the existing Supabase "avatars" bucket.
-- This column holds the public URL (or identifier) returned after upload.

ALTER TABLE public.events
    ADD COLUMN IF NOT EXISTS banner_url TEXT;
