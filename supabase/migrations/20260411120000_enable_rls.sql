-- Set up RLS for all tables
ALTER TABLE tiers ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_methods ENABLE ROW LEVEL SECURITY;
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE events ENABLE ROW LEVEL SECURITY;
ALTER TABLE tags ENABLE ROW LEVEL SECURITY;
ALTER TABLE event_tags ENABLE ROW LEVEL SECURITY;
ALTER TABLE event_participants ENABLE ROW LEVEL SECURITY;
ALTER TABLE friend_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE friendships ENABLE ROW LEVEL SECURITY;
ALTER TABLE event_chats ENABLE ROW LEVEL SECURITY;
ALTER TABLE preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE logs ENABLE ROW LEVEL SECURITY;

-- 1. Events, Tags, and Event Tags are public (anyone can search and see them)
CREATE POLICY "Public read access for events" 
ON events FOR SELECT USING (true);

CREATE POLICY "Public read access for tags" 
ON tags FOR SELECT USING (true);

CREATE POLICY "Public read access for event_tags" 
ON event_tags FOR SELECT USING (true);

-- 2. Authenticated-only read access policies for all other tables
CREATE POLICY "Auth read access for tiers" 
ON tiers FOR SELECT TO authenticated USING (true);

CREATE POLICY "Auth read access for payment_methods" 
ON payment_methods FOR SELECT TO authenticated USING (true);

CREATE POLICY "Auth read access for profiles" 
ON profiles FOR SELECT TO authenticated USING (true);

CREATE POLICY "Auth read access for invoices" 
ON invoices FOR SELECT TO authenticated USING (true);

CREATE POLICY "Auth read access for event_participants" 
ON event_participants FOR SELECT TO authenticated USING (true);

CREATE POLICY "Auth read access for friend_requests" 
ON friend_requests FOR SELECT TO authenticated USING (true);

CREATE POLICY "Auth read access for friendships" 
ON friendships FOR SELECT TO authenticated USING (true);

CREATE POLICY "Auth read access for event_chats" 
ON event_chats FOR SELECT TO authenticated USING (true);

CREATE POLICY "Auth read access for preferences" 
ON preferences FOR SELECT TO authenticated USING (true);

CREATE POLICY "Auth read access for logs" 
ON logs FOR SELECT TO authenticated USING (true);

-- 3. Authenticated-only insert/update/delete access policies (Baseline)
-- Depending on your exact needs, these might need narrowing to specific user_id.
-- But to preserve backend function while enabling "only authenticated people can see"
-- we enable write operations for authenticated users as a starting baseline.

CREATE POLICY "Auth all access for profiles" 
ON profiles FOR ALL TO authenticated USING (true);

CREATE POLICY "Auth all access for events" 
ON events FOR ALL TO authenticated USING (true);

CREATE POLICY "Auth all access for invoices" 
ON invoices FOR ALL TO authenticated USING (true);

CREATE POLICY "Auth all access for event_participants" 
ON event_participants FOR ALL TO authenticated USING (true);

CREATE POLICY "Auth all access for friend_requests" 
ON friend_requests FOR ALL TO authenticated USING (true);

CREATE POLICY "Auth all access for friendships" 
ON friendships FOR ALL TO authenticated USING (true);

CREATE POLICY "Auth all access for event_chats" 
ON event_chats FOR ALL TO authenticated USING (true);

CREATE POLICY "Auth all access for preferences" 
ON preferences FOR ALL TO authenticated USING (true);

CREATE POLICY "Auth all access for logs" 
ON logs FOR ALL TO authenticated USING (true);
