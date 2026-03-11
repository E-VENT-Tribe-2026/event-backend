# supabase

This folder holds SQL migrations and notes for applying schema/seed changes to your Supabase project.

Quick usage
-----------

Prerequisites:
- Install the Supabase CLI (`supabase`) or use `npx supabase`.
- Have your `SUPABASE_URL` and either be logged in with `supabase login` or have `SUPABASE_SERVICE_ROLE_KEY` available.

Common commands (run from repository root):

```powershell
# login (opens browser)
supabase login

# link local project to remote Supabase project (use the subdomain from SUPABASE_URL)
supabase link --project-ref <your-project-ref>

# push SQL migrations in supabase/migrations to the remote DB
npx supabase db push
# or
supabase db push
```

How migrations work
-------------------
- Place SQL migration files in `supabase/migrations/` with a timestamped filename, e.g. `20260311_add_seed_rows.sql`.
- `db push` will list pending files and ask for confirmation before applying them.
- Keep migrations simple and idempotent (use `ON CONFLICT DO NOTHING` or conditional `INSERT` where appropriate).

Notes for this project
----------------------
- The project schema references `auth.users` and uses `UUID` keys for `profiles` and `events`.
- If a migration inserts a `profiles` row, ensure the referenced `auth.users` row exists first (or insert a minimal `auth.users` row in the same migration).
- CI: prefer running `npx supabase db push` with `SUPABASE_SERVICE_ROLE_KEY` set as a secret (do not commit the key).

Example minimal migration (insert one profile + one event)
---------------------------------------------------------

```sql
-- optional: ensure auth user exists
INSERT INTO auth.users (id, aud, role, email, created_at)
VALUES ('00000000-0000-4000-8000-000000000001'::uuid, 'authenticated', 'authenticated', 'seed.user@example.com', now())
ON CONFLICT (id) DO NOTHING;

INSERT INTO profiles (id, full_name, phone, avatar_url, bio, visibility, created_at)
VALUES ('00000000-0000-4000-8000-000000000001'::uuid, 'Seed User', '+10000000000', NULL, 'Seed profile for local/dev use', 'public', now())
ON CONFLICT (id) DO NOTHING;

INSERT INTO events (id, title, description, category, cost, max_capacity, start_datetime, end_datetime, location_name, latitude, longitude, created_by, created_at, status)
VALUES ('00000000-0000-4000-8000-000000000100'::uuid, 'Seed Event', 'Simple seeded event for local/dev', 'outdoors', 0, 50, now() + INTERVAL '1 day', now() + INTERVAL '1 day' + INTERVAL '2 hours', 'Central Park', 40.785091, -73.968285, '00000000-0000-4000-8000-000000000001'::uuid, now(), 'active')
ON CONFLICT (id) DO NOTHING;
```

If you want, I can add the above minimal SQL into `supabase/migrations/` and run `npx supabase db push` here (you'll need to be logged in or provide the service role key). 
