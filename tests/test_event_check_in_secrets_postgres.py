"""PostgreSQL role-behaviour contract for issue #265 check-in secrets.

This test is deliberately test-first.  It applies the existing event/check-in
migrations, then discovers and applies the future issue #265 security migration
by its required ``Issue #265`` marker.  Until that migration exists, this test
fails with a precise message instead of silently testing a fixture-only ACL.

Run only against a disposable PostgreSQL database controlled by a superuser:

    EVENT_CHECK_IN_SECRETS_TEST_DATABASE_URL=postgresql://postgres:pw@localhost:5432/scratch \
        pytest tests/test_event_check_in_secrets_postgres.py -q

The suite is skipped unless the environment variable is present and refuses a
database that already contains ``public.events``.  Every schema/data change is
inside one transaction and is rolled back at teardown.  It never contacts a
Supabase project.
"""
import json
import os
import re
import uuid
from pathlib import Path

import pytest


DB_URL = os.environ.get("EVENT_CHECK_IN_SECRETS_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DB_URL, reason="EVENT_CHECK_IN_SECRETS_TEST_DATABASE_URL not set"
)

MIGRATIONS = Path(__file__).resolve().parents[1] / "supabase" / "migrations"
CHECK_IN_MIGRATION = "20261025210000_event_check_ins.sql"
RLS_MIGRATION = "20260411120000_enable_rls.sql"
SECRET_COLUMNS = ("check_in_code", "check_in_qr_content")
PUBLIC_COLUMNS = (
    "id", "title", "description", "category", "cost", "max_capacity", "status",
    "start_datetime", "end_datetime", "location_name", "latitude", "longitude",
    "created_by", "qr_link", "privacy", "created_at", "updated_at",
    "cancellation_reason", "banner_url", "removed_at", "removed_by",
)
EVENT_ID = str(uuid.uuid4())
ORGANIZER_ID = str(uuid.uuid4())


STANDINS = """
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then create role anon nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then create role service_role nologin; end if;
end $$;
alter role service_role bypassrls;
create schema if not exists auth;
create table public.profiles (id uuid primary key);
create table public.events (
  id uuid primary key,
  title varchar not null,
  description text,
  category varchar,
  cost bigint default 0,
  max_capacity bigint,
  status varchar default 'active',
  start_datetime timestamptz,
  end_datetime timestamptz,
  location_name varchar,
  latitude numeric,
  longitude numeric,
  created_by uuid references public.profiles(id) on delete set null,
  qr_link text,
  privacy varchar default 'public',
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  cancellation_reason text,
  banner_url text,
  removed_at timestamptz,
  removed_by uuid references public.profiles(id) on delete set null
);
"""


def _read(name: str) -> str:
    return (MIGRATIONS / name).read_text(encoding="utf-8")


def _events_rls_sql() -> str:
    """Extract the existing events RLS statements without unrelated tables."""
    source = re.sub(r"--[^\n]*", "", _read(RLS_MIGRATION))
    statements = [
        statement
        for statement in source.split(";")
        if re.search(r"public\.events\b", statement)
    ]
    assert statements, "events RLS statements not found"
    return ";\n".join(statements) + ";"


def _issue_265_migration() -> Path:
    """Require a deliberately marked production migration; never guess its filename."""
    matches = [
        path
        for path in MIGRATIONS.glob("*.sql")
        if re.search(r"\bissue\s*#?265\b", path.read_text(encoding="utf-8"), re.I)
    ]
    if not matches:
        pytest.fail(
            "Issue #265 security migration is not present. Add one under supabase/migrations "
            "with an 'Issue #265' marker, then this test will apply it to the scratch database."
        )
    assert len(matches) == 1, f"expected one Issue #265 migration, found: {matches}"
    return matches[0]


def _seed_vulnerable_acl(cur) -> None:
    """Model the verified pre-fix broad grants, including a PUBLIC grant path."""
    cur.execute("grant usage on schema public to public, anon, authenticated, service_role")
    cur.execute("grant select on public.events to public, anon, authenticated, service_role")
    # Explicit column ACLs make a regression visible even if a migration only revokes table ACLs.
    cur.execute(
        "grant select (check_in_code, check_in_qr_content) on public.events "
        "to anon, authenticated"
    )


@pytest.fixture(scope="module")
def conn():
    psycopg2 = pytest.importorskip("psycopg2")
    connection = psycopg2.connect(DB_URL)
    cur = connection.cursor()
    cur.execute("select to_regclass('public.events')")
    if cur.fetchone()[0] is not None:
        connection.close()
        pytest.skip("public.events already exists; refusing to run against a non-scratch database")
    try:
        cur.execute(STANDINS)
        cur.execute(_read(CHECK_IN_MIGRATION))
        cur.execute(_events_rls_sql())
        _seed_vulnerable_acl(cur)
        # This is the intended red-to-green seam: the future migration must remove every
        # effective anon/authenticated secret path while retaining the service-role path.
        cur.execute(_issue_265_migration().read_text(encoding="utf-8"))
        cur.execute("insert into public.profiles(id) values (%s)", (ORGANIZER_ID,))
        cur.execute(
            "insert into public.events "
            "(id, title, status, created_by, privacy, check_in_code, check_in_qr_content) "
            "values (%s, 'Public event', 'active', %s, 'public', '482913', '482913')",
            (EVENT_ID, ORGANIZER_ID),
        )
        yield connection
    finally:
        connection.rollback()
        connection.close()


@pytest.fixture
def cur(conn):
    cursor = conn.cursor()
    cursor.execute("savepoint issue_265_test")
    yield cursor
    cursor.execute("rollback to savepoint issue_265_test")
    cursor.close()


def _act_as(cur, role: str) -> None:
    cur.execute("reset role")
    cur.execute(f"set local role {role}")
    cur.execute(
        "select set_config('request.jwt.claims', %s, true)",
        (json.dumps({"role": role}),),
    )


def _privilege(cur, role: str, column: str | None = None) -> bool:
    if column is None:
        cur.execute("select has_table_privilege(%s, 'public.events', 'select')", (role,))
    else:
        cur.execute(
            "select has_column_privilege(%s, 'public.events', %s, 'select')",
            (role, column),
        )
    return cur.fetchone()[0]


def _public_acl_selects(cur, column: str | None = None) -> bool:
    if column is None:
        cur.execute(
            "select exists (select 1 from pg_class c cross join lateral aclexplode(c.relacl) a "
            "where c.oid = 'public.events'::regclass and a.grantee = 0 "
            "and a.privilege_type = 'SELECT')"
        )
    else:
        cur.execute(
            "select exists (select 1 from pg_attribute a cross join lateral aclexplode(a.attacl) x "
            "where a.attrelid = 'public.events'::regclass and a.attname = %s "
            "and x.grantee = 0 and x.privilege_type = 'SELECT')",
            (column,),
        )
    return cur.fetchone()[0]


def _inherited_secret_grantees(cur, role: str) -> list[str]:
    """List parent roles that could make a caller a secret reader through inheritance."""
    cur.execute(
        "with recursive parents(member, roleid) as ("
        "  select member, roleid from pg_auth_members "
        "  union "
        "  select p.member, m.roleid from parents p join pg_auth_members m on m.member = p.roleid"
        ") "
        "select distinct parent.rolname from parents p join pg_roles child on child.oid = p.member "
        "join pg_roles parent on parent.oid = p.roleid "
        "where child.rolname = %s and ("
        "has_column_privilege(parent.oid, 'public.events', 'check_in_code', 'select') "
        "or has_column_privilege(parent.oid, 'public.events', 'check_in_qr_content', 'select'))",
        (role,),
    )
    return [row[0] for row in cur.fetchall()]


@pytest.mark.parametrize("role", ("anon", "authenticated"))
def test_public_roles_have_no_table_or_secret_column_select(role, cur):
    assert not _privilege(cur, role), f"{role} still has table-level SELECT"
    for column in SECRET_COLUMNS:
        assert not _privilege(cur, role, column), f"{role} can still SELECT {column}"
    assert _inherited_secret_grantees(cur, role) == []


def test_public_has_no_effective_secret_grant_path(cur):
    # A grant to PUBLIC reaches both anon and authenticated, bypassing direct-role revokes.
    assert not _public_acl_selects(cur)
    for column in SECRET_COLUMNS:
        assert not _public_acl_selects(cur, column)


@pytest.mark.parametrize("role", ("anon", "authenticated"))
def test_public_roles_can_read_public_columns_and_visible_event_rows(role, cur):
    _act_as(cur, role)
    cur.execute(
        "select id, title, status, start_datetime, created_by, privacy "
        "from public.events where id = %s",
        (EVENT_ID,),
    )
    rows = cur.fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert (str(row[0]), row[1], row[2], row[3], str(row[4]), row[5]) == (
        EVENT_ID, "Public event", "active", None, ORGANIZER_ID, "public"
    )
    for column in PUBLIC_COLUMNS:
        assert _privilege(cur, role, column), f"{role} lost safe column {column}"


@pytest.mark.parametrize("role", ("anon", "authenticated"))
@pytest.mark.parametrize("column", SECRET_COLUMNS)
def test_public_roles_cannot_select_check_in_secrets(role, column, cur):
    psycopg2 = pytest.importorskip("psycopg2")
    _act_as(cur, role)
    cur.execute("savepoint secret_denied")
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
        cur.execute(f"select {column} from public.events where id = %s", (EVENT_ID,))
    cur.execute("rollback to savepoint secret_denied")


def test_service_role_retains_backend_event_and_secret_access(cur):
    _act_as(cur, "service_role")
    assert _privilege(cur, "service_role")
    for column in (*PUBLIC_COLUMNS, *SECRET_COLUMNS):
        assert _privilege(cur, "service_role", column)
    cur.execute(
        "select id, title, status, start_datetime, created_by, check_in_code, check_in_qr_content "
        "from public.events where id = %s",
        (EVENT_ID,),
    )
    assert cur.fetchone()[5:] == ("482913", "482913")
