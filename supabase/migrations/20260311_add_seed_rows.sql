-- optional: ensure an auth user exists for the profile FK
INSERT INTO auth.users (id, aud, role, email, created_at)
VALUES ('00000000-0000-4000-8000-000000000001'::uuid, 'authenticated', 'authenticated', 'seed.user@example.com', now())
ON CONFLICT (id) DO NOTHING;

-- insert one profile
INSERT INTO profiles (id, full_name, phone, avatar_url, bio, visibility, created_at)
VALUES (
  '00000000-0000-4000-8000-000000000001'::uuid,
  'Seed User',
  '+10000000000',
  NULL,
  'Seed profile for local/dev use',
  'public',
  now()
)
ON CONFLICT (id) DO NOTHING;

-- insert one event created by that profile
INSERT INTO events (id, title, description, category, cost, max_capacity, start_datetime, end_datetime, location_name, latitude, longitude, created_by, created_at, status)
VALUES (
  '00000000-0000-4000-8000-000000000100'::uuid,
  'Seed Event',
  'Simple seeded event for local/dev',
  'outdoors',
  0,
  50,
  now() + INTERVAL '1 day',
  now() + INTERVAL '1 day' + INTERVAL '2 hours',
  'Central Park',
  40.785091,
  -73.968285,
  '00000000-0000-4000-8000-000000000001'::uuid,
  now(),
  'active'
)
ON CONFLICT (id) DO NOTHING;