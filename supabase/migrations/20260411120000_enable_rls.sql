-- =============================================================================
-- Migration: 20260411120000_enable_rls.sql
-- Description: Enable RLS and baseline policies across public tables.
--              Updated to be idempotent and safe across fresh and existing environments.
-- =============================================================================

-- Set up RLS for all tables (guarded with IF EXISTS)
ALTER TABLE IF EXISTS public.tiers ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.payment_methods ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.events ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.tags ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.event_tags ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.event_participants ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.friend_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.friendships ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.event_chats ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.logs ENABLE ROW LEVEL SECURITY;

-- 1. Events, Tags, and Event Tags are public (anyone can search and see them)
DROP POLICY IF EXISTS "Public read access for events" ON public.events;
CREATE POLICY "Public read access for events" 
ON public.events FOR SELECT USING (true);

DROP POLICY IF EXISTS "Public read access for tags" ON public.tags;
CREATE POLICY "Public read access for tags" 
ON public.tags FOR SELECT USING (true);

DROP POLICY IF EXISTS "Public read access for event_tags" ON public.event_tags;
CREATE POLICY "Public read access for event_tags" 
ON public.event_tags FOR SELECT USING (true);

-- 2. Authenticated-only read access policies for all other tables
DROP POLICY IF EXISTS "Auth read access for tiers" ON public.tiers;
CREATE POLICY "Auth read access for tiers" 
ON public.tiers FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS "Auth read access for payment_methods" ON public.payment_methods;
CREATE POLICY "Auth read access for payment_methods" 
ON public.payment_methods FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS "Auth read access for profiles" ON public.profiles;
CREATE POLICY "Auth read access for profiles" 
ON public.profiles FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS "Auth read access for invoices" ON public.invoices;
CREATE POLICY "Auth read access for invoices" 
ON public.invoices FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS "Auth read access for event_participants" ON public.event_participants;
CREATE POLICY "Auth read access for event_participants" 
ON public.event_participants FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS "Auth read access for friend_requests" ON public.friend_requests;
CREATE POLICY "Auth read access for friend_requests" 
ON public.friend_requests FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS "Auth read access for friendships" ON public.friendships;
CREATE POLICY "Auth read access for friendships" 
ON public.friendships FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS "Auth read access for event_chats" ON public.event_chats;
CREATE POLICY "Auth read access for event_chats" 
ON public.event_chats FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS "Auth read access for preferences" ON public.preferences;
CREATE POLICY "Auth read access for preferences" 
ON public.preferences FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS "Auth read access for logs" ON public.logs;
CREATE POLICY "Auth read access for logs" 
ON public.logs FOR SELECT TO authenticated USING (true);

-- 3. Authenticated-only insert/update/delete access policies (Baseline)
DROP POLICY IF EXISTS "Auth all access for profiles" ON public.profiles;
CREATE POLICY "Auth all access for profiles" 
ON public.profiles FOR ALL TO authenticated USING (true);

DROP POLICY IF EXISTS "Auth all access for events" ON public.events;
CREATE POLICY "Auth all access for events" 
ON public.events FOR ALL TO authenticated USING (true);

DROP POLICY IF EXISTS "Auth all access for invoices" ON public.invoices;
CREATE POLICY "Auth all access for invoices" 
ON public.invoices FOR ALL TO authenticated USING (true);

DROP POLICY IF EXISTS "Auth all access for event_participants" ON public.event_participants;
CREATE POLICY "Auth all access for event_participants" 
ON public.event_participants FOR ALL TO authenticated USING (true);

DROP POLICY IF EXISTS "Auth all access for friend_requests" ON public.friend_requests;
CREATE POLICY "Auth all access for friend_requests" 
ON public.friend_requests FOR ALL TO authenticated USING (true);

DROP POLICY IF EXISTS "Auth all access for friendships" ON public.friendships;
CREATE POLICY "Auth all access for friendships" 
ON public.friendships FOR ALL TO authenticated USING (true);

DROP POLICY IF EXISTS "Auth all access for event_chats" ON public.event_chats;
CREATE POLICY "Auth all access for event_chats" 
ON public.event_chats FOR ALL TO authenticated USING (true);

DROP POLICY IF EXISTS "Auth all access for preferences" ON public.preferences;
CREATE POLICY "Auth all access for preferences" 
ON public.preferences FOR ALL TO authenticated USING (true);

DROP POLICY IF EXISTS "Auth all access for logs" ON public.logs;
CREATE POLICY "Auth all access for logs" 
ON public.logs FOR ALL TO authenticated USING (true);
