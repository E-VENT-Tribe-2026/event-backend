"""Migration-text tests for the event_participants read guard (ticket #257).

Test-first: supabase/migrations/20261112120000_event_participants_read_guard.sql
must add a RESTRICTIVE SELECT policy on public.event_participants plus three RESTRICTIVE
write-lock policies (no direct INSERT/UPDATE/DELETE), all layered over the untouched
baseline permissive policies, two SECURITY DEFINER helpers
(is_event_organizer / is_event_participant), a supporting index, and redefine the
shared is_administrator() helper identically to 20261111120000. No DB or network.

Executable-SQL assertions run on comment-stripped text (so the commented rollback
cannot satisfy them); banner/rollback assertions use raw text.
"""
import re
from pathlib import Path

import pytest

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "supabase" / "migrations"
MIGRATION_NAME = "20261112120000_event_participants_read_guard.sql"
ADMIN_MIGRATION_NAME = "20261111120000_removed_content_rls_guards.sql"
DEPENDENCIES = [
    "20260101000000_initial_schema.sql",
    "20260411120000_enable_rls.sql",
]
NAME_RE = re.compile(r"^\d{14}_[a-z0-9_]+\.sql$")

POLICY = "event_participants_read_guard"
NO_INSERT = "event_participants_no_direct_insert"
NO_UPDATE = "event_participants_no_direct_update"
NO_DELETE = "event_participants_no_direct_delete"
ALL_POLICIES = [POLICY, NO_INSERT, NO_UPDATE, NO_DELETE]
INDEX = "event_participants_event_user_idx"
HELPERS = {"is_event_organizer": "uuid", "is_event_participant": "uuid", "is_administrator": ""}
NEW_HELPERS = ("is_event_organizer", "is_event_participant")
BASELINE_POLICIES = [
    "Auth read access for event_participants",
    "Auth all access for event_participants",
]


def _sql(raw: str) -> str:
    """Executable SQL: comments stripped, lowercased, whitespace collapsed."""
    no_comments = re.sub(r"--[^\n]*", "", raw)
    return re.sub(r"\s+", " ", no_comments.lower()).strip()


def _compact(s: str) -> str:
    """Drop spaces around parentheses/operators so formatting does not matter."""
    return re.sub(r" ?(\(|\)|=|<>|->>|,) ?", r"\1", s)


def _statements(sql: str):
    return [s.strip() for s in sql.split(";")]


def _banner(raw: str) -> str:
    out = []
    for l in raw.splitlines():
        if l.strip() and not l.lstrip().startswith("--"):
            break
        if l.lstrip().startswith("--"):
            out.append(l)
    return "\n".join(out)


def _flat_banner(raw: str) -> str:
    return re.sub(r"\s*\n--\s*", " ", _banner(raw).lower())


def _function_def(c: str, fn: str) -> str:
    """create or replace function public.<fn>(...) ... $$; (on compacted sql)."""
    m = re.search(rf"create or replace function public\.{fn}\(", c)
    assert m, f"CREATE OR REPLACE FUNCTION public.{fn} missing"
    end = re.search(r"\$\$;", c[m.end():])
    assert end, f"{fn}: body not terminated with $$;"
    return c[m.start(): m.end() + end.end()]


@pytest.fixture(scope="module")
def raw() -> str:
    path = MIGRATIONS_DIR / MIGRATION_NAME
    if not path.is_file():
        pytest.fail(f"Migration {MIGRATION_NAME} not found in {MIGRATIONS_DIR}")
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def sql(raw) -> str:
    return _sql(raw)


# ---------- file / ordering ----------

def test_filename_format_and_ordering():
    assert NAME_RE.match(MIGRATION_NAME)
    for dep in DEPENDENCIES:
        assert (MIGRATIONS_DIR / dep).is_file(), f"dependency migration {dep} is missing"
        assert MIGRATION_NAME > dep, f"{MIGRATION_NAME} must sort after {dep}"
    assert (MIGRATIONS_DIR / MIGRATION_NAME).is_file(), \
        f"Migration {MIGRATION_NAME} not found in {MIGRATIONS_DIR}"


# ---------- banner ----------

def _in_order(flat: str, *patterns: str) -> None:
    """Each regex must match, in the given order, in the flattened banner."""
    pos = 0
    for p in patterns:
        m = re.compile(p).search(flat, pos)
        assert m, f"banner phrase {p!r} missing (or out of order) after offset {pos}"
        pos = m.end()


def test_banner_mentions_required_topics(raw):
    assert raw.lstrip().startswith("--"), "file must start with a banner comment"
    banner = _banner(raw)
    flat = _flat_banner(raw)
    assert "ticket #257: participant list privacy via direct supabase access" in flat
    assert "related requirement: backend #187" in flat
    assert not re.search(r"ticket #257 \(", flat), "ticket line must use the sibling format"
    # realtime: INSERT/UPDATE filtered, DELETE not filtered, counters stop updating
    _in_order(
        flat,
        r"realtime: insert and update realtime payloads are filtered by this policy",
        r"outsiders \(non-participants\) no longer receive other users' participant rows",
        r"delete events are not filtered by rls in supabase realtime",
        r"may still reach outsiders with minimal key columns",
        r"homepage attendee counters that rely on participant realtime insert events "
        r"will stop updating for non-participants",
        r"count and friends-attending data stay available through the backend endpoints "
        r"/participants/count and /participants/friends",
    )
    # frontend verification
    _in_order(
        flat,
        r"frontend verification: the frontend main and dev branches do not use this table directly",
        r"before applying, still verify that no other client \(for example a mobile app\) "
        r"writes or reads event_participants directly through supabase",
    )
    assert re.search(r"select\b[^\n]*\bfrom pg_policies", banner, re.I), \
        "banner must contain the pg_policies pre-flight select"
    _in_order(flat, r"pre-flight: inspect the current policies",
              r"select policyname, permissive, roles, cmd, qual, with_check from pg_policies")
    # anon keeps EXECUTE, with the reason
    _in_order(
        flat,
        r"execute on the helpers stays granted to anon and authenticated on purpose",
        r"restrictive policy expressions may be evaluated for anon",
        r"a missing grant would produce a permission error instead of an empty result",
    )
    # writes: direct writes denied by three restrictive policies
    _in_order(
        flat,
        r"writes: direct insert, update and delete on event_participants are now denied to "
        r"anon and authenticated by three restrictive policies",
        r'"event_participants_no_direct_insert"',
        r'"event_participants_no_direct_update"',
        r'"event_participants_no_direct_delete"',
        r"the open baseline for all policy",
        r"let any signed-in user create their own participant row and thereby read the "
        r"participant list, bypass the backend join checks \(blocked/hidden/cancelled, "
        r"notifications\), forge rows and delete rows",
        r"only the backend \(service role, which has bypassrls\) writes participants",
        r"the backend performs all participant writes \(join, leave and remove endpoints\) "
        r"with the service role",
        r"the frontend \(e-vent-tribe-2026/event-frontend, main and dev branches were checked\) "
        r"never reads or writes event_participants directly",
        r"it uses supabase for auth and realtime only",
        r"subscribes to a table named 'participants', which does not exist in this schema",
    )
    assert "no write policy is added" not in flat
    assert "a plain insert is unchanged" not in flat


def test_rollback_section_is_commented_out_only(raw, sql):
    lines = raw.splitlines()
    assert any(re.match(r"\s*--.*rollback", l, re.I) for l in lines), "rollback comment section missing"
    assert re.search(r"emergency", raw, re.I), "rollback must be labelled emergency-only"
    expected = [
        f'-- DROP POLICY IF EXISTS "{NO_DELETE}" ON public.event_participants;',
        f'-- DROP POLICY IF EXISTS "{NO_UPDATE}" ON public.event_participants;',
        f'-- DROP POLICY IF EXISTS "{NO_INSERT}" ON public.event_participants;',
        f'-- DROP POLICY IF EXISTS "{POLICY}" ON public.event_participants;',
        f"-- DROP INDEX IF EXISTS public.{INDEX};",
        "-- DROP FUNCTION IF EXISTS public.is_event_participant(uuid);",
        "-- DROP FUNCTION IF EXISTS public.is_event_organizer(uuid);",
    ]
    stripped = [l.strip() for l in lines]
    positions = []
    for e in expected:
        assert e in stripped, f"commented rollback line missing: {e}"
        positions.append(stripped.index(e))
    assert positions == sorted(positions), \
        "rollback order must be the four policies, index, participant helper, organizer helper"
    low = raw.lower()
    rb = re.sub(r"\s*\n--\s*", " ", low[low.index("emergency"):])
    assert "reopens both the read hole and direct writes" in rb
    assert "is_administrator()" in rb and "20261111120000" in rb and "shared" in rb, \
        "rollback must note is_administrator() is shared with 20261111120000"
    assert re.search(r"not dropped|do not drop|not drop|never drop", rb), \
        "rollback must say is_administrator() is NOT dropped"
    _in_order(
        rb,
        r"roll this migration back \(drop event_participants_read_guard\) before running "
        r"the 20261111120000 rollback",
        r"that rollback drops is_administrator\(\) which this policy depends on",
        r"never use cascade",
    )
    assert "drop function" not in sql, "DROP FUNCTION must only appear inside comments"
    assert "drop index" not in sql, "DROP INDEX must only appear inside comments"
    drops = [s for s in _statements(sql) if re.search(r"(^| )drop ", s)]
    assert len(drops) == 4 and all(
        d.endswith(f'drop policy if exists "{n}" on public.event_participants')
        for d, n in zip(drops, ALL_POLICIES)), drops


# ---------- helper functions ----------

@pytest.mark.parametrize("fn,arg", HELPERS.items())
def test_helper_definition(sql, fn, arg):
    body = _function_def(_compact(sql), fn)
    assert re.match(rf"create or replace function public\.{fn}\({arg}(?: [a-z_]+)?\)", body)
    assert "returns boolean" in body
    assert "security definer" in body
    assert re.search(r"\bstable\b", body)
    assert re.search(r"set search_path(=| to )''", body), "search_path must be pinned to the empty string"


@pytest.mark.parametrize("fn,arg", HELPERS.items())
def test_helper_privileges(sql, fn, arg):
    c = _compact(sql)
    assert re.search(rf"revoke all on function public\.{fn}\({arg}\) ?from public", c), \
        f"{fn}: EXECUTE must be revoked from public"
    m = re.search(rf"grant execute on function public\.{fn}\({arg}\) ?to ([a-z_, ]+)", c)
    assert m, f"{fn}: GRANT EXECUTE missing"
    assert {r.strip() for r in m.group(1).split(",")} == {"anon", "authenticated"}


def test_search_path_empty_exactly_three_functions(sql):
    assert len(re.findall(r"set search_path ?(=|to) ?''", sql)) == 3
    assert "pg_temp" not in sql
    assert not re.search(r"search_path (=|to) (?!'')", sql), "search_path must only ever be set to ''"


def test_is_event_organizer_logic(sql):
    body = _function_def(_compact(sql), "is_event_organizer")
    assert "public.events" in body
    assert re.search(r"created_by=auth\.uid\(\)", body)
    assert "=$1" in body, "must filter by the event id argument"
    assert "event_participants" not in body, "organizer must not depend on participant rows"


def test_is_event_participant_logic(sql):
    body = _function_def(_compact(sql), "is_event_participant")
    assert "public.event_participants" in body
    assert re.search(r"user_id=auth\.uid\(\)", body)
    assert re.search(r"event_id=\$1", body)
    assert "status" not in body, "any participant status counts"


def test_helper_bodies_are_schema_qualified(sql):
    c = _compact(sql)
    for fn in NEW_HELPERS:
        inner = _function_def(c, fn).split("as $$", 1)[1]
        assert not re.search(r"\b(from|join) (?!public\.)[a-z_]+", inner), f"{fn}: unqualified table in body"
        assert re.search(r"(?<![\w.])auth\.uid\(\)", inner)
        assert not re.search(r"(?<![\w.])uid\(\)", inner)


def test_is_administrator_logic(sql):
    body = _function_def(_compact(sql), "is_administrator")
    assert "auth.uid()" in body
    assert "role='administrator'" in body
    assert "(auth.jwt()->>'aal')='aal2'" in body
    assert "public.profiles" in body


def test_is_administrator_matches_removed_content_migration(sql):
    other = MIGRATIONS_DIR / ADMIN_MIGRATION_NAME
    if not other.is_file():
        pytest.skip(f"{ADMIN_MIGRATION_NAME} not present; nothing to compare is_administrator against")
    other_sql = _sql(other.read_text(encoding="utf-8"))

    def pieces(s):
        fn = _function_def(_compact(s), "is_administrator")
        c = _compact(s)
        rev = re.search(r"revoke all on function public\.is_administrator\(\) ?from public;", c)
        gr = re.search(r"grant execute on function public\.is_administrator\(\) ?to [a-z_, ]+;", c)
        assert rev and gr
        return fn, rev.group(0), gr.group(0)

    assert pieces(sql) == pieces(other_sql)


# ---------- policy ----------

def _policy_stmts(sql):
    return [s for s in _statements(sql) if re.search(r"(^| )create policy ", s)]


def _stmt_for(sql, name):
    found = [s for s in _policy_stmts(sql) if f'create policy "{name}" ' in s]
    assert len(found) == 1, (name, found)
    return found[0]


def test_exactly_four_policies_created_all_restrictive(sql):
    stmts = _policy_stmts(sql)
    assert len(stmts) == 4, stmts
    assert set(re.findall(r'create policy "([^"]+)"', sql)) == set(ALL_POLICIES)
    for s in stmts:
        assert re.search(r'create policy "[^"]+" on public\.event_participants as restrictive for ', s), s
        assert " to " not in re.split(r"using|with check", s, maxsplit=1)[0], \
            "policy must apply to all roles"
    assert "permissive" not in sql, "no PERMISSIVE policy may be created"
    assert not re.search(r" for all\b", sql), "no ALL policy may be created"


def test_read_guard_is_restrictive_select_only(sql):
    stmt = _stmt_for(sql, POLICY)
    assert re.search(
        rf'create policy "{POLICY}" on public\.event_participants as restrictive for select\b', stmt), stmt
    assert not re.search(r" for (insert|update|delete|all)\b", stmt)
    assert "with check" not in stmt


def test_policy_predicate_has_four_parts(sql):
    stmt = _compact(_stmt_for(sql, POLICY))
    m = re.search(r"using\((.*)\)$", stmt)
    assert m, stmt
    using = m.group(1)
    for p in (r"user_id=auth\.uid\(\)",
              r"public\.is_event_organizer\(event_id\)",
              r"public\.is_event_participant\(event_id\)",
              r"public\.is_administrator\(\)"):
        assert re.search(p, using), f"policy USING missing {p}: {using}"
    assert len(re.findall(r"\bor\b", using)) == 3
    assert " and " not in using


def test_write_lock_policies(sql):
    ins = _compact(_stmt_for(sql, NO_INSERT))
    assert ins.endswith("as restrictive for insert with check(false)"), ins
    assert "using" not in ins
    upd = _compact(_stmt_for(sql, NO_UPDATE))
    assert upd.endswith("as restrictive for update using(false)with check(false)"), upd
    dele = _compact(_stmt_for(sql, NO_DELETE))
    assert dele.endswith("as restrictive for delete using(false)"), dele
    assert "with check" not in dele


def test_drop_policy_precedes_create_policy_for_each(sql):
    stmts = _statements(sql)
    creates = [i for i, s in enumerate(stmts) if re.search(r"(^| )create policy ", s)]
    assert len(creates) == 4
    for i in creates:
        name = re.search(r'create policy "([^"]+)"', stmts[i]).group(1)
        assert i > 0 and stmts[i - 1].endswith(
            f'drop policy if exists "{name}" on public.event_participants'), name


# ---------- index ----------

def test_index_definition(sql):
    c = _compact(sql)
    m = re.search(
        rf"create (unique )?index if not exists {INDEX} on public\.event_participants ?(?:using btree ?)?\(([^)]*)\)", c)
    assert m, "CREATE INDEX IF NOT EXISTS event_participants_event_user_idx missing"
    assert m.group(1) is None, "index must be non-unique"
    assert [x.strip() for x in m.group(2).split(",")] == ["event_id", "user_id"]
    assert "unique" not in sql


# ---------- idempotence ----------

def test_idempotent_statements(sql):
    assert len(re.findall(r"create or replace function public\.", sql)) == 3
    assert not re.search(r"create function", sql)
    assert not re.search(r"create (unique )?index (?!if not exists)", sql)


# ---------- guard rails ----------

def test_baseline_policies_untouched(sql):
    for name in BASELINE_POLICIES:
        assert name.lower() not in sql, f"baseline policy {name!r} must not be referenced"
    assert "alter policy" not in sql
    assert "alter table" not in sql
    assert "disable row level security" not in sql


def test_no_bypass_tricks(sql):
    assert "service_role" not in sql
    assert "bypassrls" not in sql
    assert "permissive" not in sql
