"""Migration-text tests for the removed-content RLS guards migration.

Test-first: supabase/migrations/20261111120000_removed_content_rls_guards.sql
must add RESTRICTIVE policies (layered over the untouched baseline policies) that
hide and freeze removed events / chat messages from direct Supabase access, plus
two SECURITY DEFINER policy helpers (the cascade-protection trigger function is
also SECURITY DEFINER). No DB or network.

Assertions about executable SQL run on comment-stripped text (so the commented
rollback section cannot satisfy them); banner/rollback assertions use raw text.
"""
import re
from pathlib import Path

import pytest

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "supabase" / "migrations"
MIGRATION_NAME = "20261111120000_removed_content_rls_guards.sql"
DEPENDENCIES = [
    "20260411120000_enable_rls.sql",
    "20260422161000_create_event_chats_table.sql",
    "20260424142000_add_type_to_event_chats.sql",
    "20261026120000_removed_events_and_messages.sql",
]
NAME_RE = re.compile(r"^\d{14}_[a-z0-9_]+\.sql$")

# policy name -> (table, command)
POLICIES = {
    "events_removed_select_guard": ("public.events", "select"),
    "events_removed_update_guard": ("public.events", "update"),
    "events_removed_delete_guard": ("public.events", "delete"),
    "event_chats_removed_select_guard": ("public.event_chats", "select"),
    "event_chats_removed_update_guard": ("public.event_chats", "update"),
    "event_chats_removed_delete_guard": ("public.event_chats", "delete"),
    "event_chats_removed_insert_guard": ("public.event_chats", "insert"),
}
HELPERS = {"is_administrator": "", "event_is_removed": "uuid"}
BASELINE_POLICIES = [
    "Public read access for events",
    "Auth all access for events",
    "Auth read access for event_chats",
    "Auth all access for event_chats",
]


def _sql(raw: str) -> str:
    """Executable SQL: comments stripped, lowercased, whitespace collapsed."""
    no_comments = re.sub(r"--[^\n]*", "", raw)
    return re.sub(r"\s+", " ", no_comments.lower()).strip()


def _compact(s: str) -> str:
    """Drop spaces around parentheses/operators so formatting does not matter."""
    return re.sub(r" ?(\(|\)|=|<>|->>) ?", r"\1", s)


def _statements(sql: str):
    return [s.strip() for s in sql.split(";")]


def _policy_stmt(sql: str, name: str) -> str:
    found = [s for s in _statements(sql) if f'create policy "{name}"' in s]
    assert len(found) == 1, f"expected exactly one CREATE POLICY {name!r}, found {len(found)}"
    return found[0]


def _banner_lines(raw: str):
    """Leading comment block (up to the first executable line)."""
    out = []
    for l in raw.splitlines():
        if l.strip() and not l.lstrip().startswith("--"):
            break
        out.append(l)
    return out


@pytest.fixture(scope="module")
def raw() -> str:
    path = MIGRATIONS_DIR / MIGRATION_NAME
    if not path.is_file():
        pytest.fail(f"Migration {MIGRATION_NAME} not found in {MIGRATIONS_DIR}")
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def sql(raw) -> str:
    return _sql(raw)


# ---------- file / banner ----------

def test_filename_format_and_ordering():
    assert NAME_RE.match(MIGRATION_NAME)
    for dep in DEPENDENCIES:
        assert (MIGRATIONS_DIR / dep).is_file(), f"dependency migration {dep} is missing"
        assert MIGRATION_NAME > dep, f"{MIGRATION_NAME} must sort after {dep}"
    assert (MIGRATIONS_DIR / MIGRATION_NAME).is_file(), f"{MIGRATION_NAME} is missing"


def test_banner_describes_event_level_hiding_and_cascade_trigger(raw):
    banner = "\n".join(l for l in _banner_lines(raw) if l.lstrip().startswith("--")).lower()
    assert re.search(r"chat messages of a removed event", banner)
    assert re.search(r"hidden", banner) and re.search(r"locked", banner)
    assert re.search(r"cascade", banner) and "trigger" in banner
    assert "anon/authenticated" in banner


def test_banner_mentions_required_topics(raw):
    assert raw.lstrip().startswith("--"), "file must start with a banner comment"
    banner = "\n".join(l for l in _banner_lines(raw) if l.lstrip().startswith("--"))
    assert re.search(r"realtime", banner, re.I), "banner must mention realtime"
    assert re.search(r"non-admin", banner, re.I), \
        "banner must say realtime does not deliver removal updates to non-admin subscribers"
    assert re.search(r"live[- ]database", banner, re.I), "banner must mention live-database verification"
    for word in ("vector", "saved_events", "notifications"):
        assert word in banner.lower(), f"banner must mention {word}"
    assert re.search(r"idempotent|safe to re-run", banner, re.I)


def test_banner_documents_search_path_grants_and_race(raw):
    banner = "\n".join(l for l in _banner_lines(raw) if l.lstrip().startswith("--")).lower()
    flat = re.sub(r"\s*\n--\s*", " ", banner)
    assert "search_path" in banner and "pg_catalog" in banner
    assert re.search(r"execute on the two policy helpers stays granted to anon", flat)
    assert "boolean" in banner
    assert "known limitation" in banner and "snapshot" in banner and "race" in banner
    # the BEFORE DELETE trigger has the same class of race (accepted, no locking)
    assert re.search(r"same class of snapshot race applies to the before delete trigger", flat)
    assert "uncommitted removal" in flat and "just-removed message" in flat
    assert "accepted" in flat and "no locking" in flat


def test_banner_says_trigger_function_is_also_security_definer(raw):
    banner = "\n".join(l for l in _banner_lines(raw) if l.lstrip().startswith("--")).lower()
    flat = re.sub(r"\s*\n--\s*", " ", banner)
    assert "two security definer policy helpers" in flat
    assert "two security definer helpers" not in flat
    assert "cascade-protection trigger function is also security definer" in flat
    assert "all three functions pin search_path" in flat


def test_rollback_section_is_commented_out_only(raw, sql):
    lines = raw.splitlines()
    assert any(re.match(r"\s*--.*rollback", l, re.I) for l in lines), "rollback comment section missing"
    assert re.search(r"emergency", raw, re.I), "rollback must be labelled emergency-only"
    for name in POLICIES:
        assert re.search(rf'^\s*--\s*drop policy if exists "{name}"', raw, re.I | re.M), \
            f"commented rollback DROP POLICY for {name} missing"
    for fn in HELPERS:
        assert re.search(rf"^\s*--\s*drop function if exists public\.{fn}\(", raw, re.I | re.M), \
            f"commented rollback DROP FUNCTION for {fn} missing"
    assert re.search(r"^\s*--\s*drop trigger if exists events_protect_removed_chats on public\.events;",
                     raw, re.I | re.M), "commented rollback DROP TRIGGER missing"
    assert re.search(rf"^\s*--\s*drop function if exists public\.{TRIGGER_FN}\(\);", raw, re.I | re.M), \
        "commented rollback DROP FUNCTION for the trigger function missing"
    rb = raw.lower()
    rb = rb[rb.index("rollback (emergency"):]
    assert rb.index("-- drop policy") < rb.index("-- drop trigger") < rb.index(f"-- drop function if exists public.{TRIGGER_FN}") \
        < rb.index("-- drop function if exists public.event_is_removed")
    assert "drop function" not in sql, "DROP FUNCTION must only appear inside comments"


# ---------- helpers ----------

def _helper_body(c: str, fn: str) -> str:
    m = re.search(rf"create or replace function public\.{fn}\(", c)
    assert m, f"CREATE OR REPLACE FUNCTION public.{fn} missing"
    nxt = re.search(r"create or replace function|create policy|drop policy", c[m.end():])
    return c[m.start(): m.end() + (nxt.start() if nxt else len(c))]


@pytest.mark.parametrize("fn,arg", HELPERS.items())
def test_helper_definition(sql, fn, arg):
    body = _helper_body(_compact(sql), fn)
    assert re.match(rf"create or replace function public\.{fn}\({arg}(?: [a-z_]+)?\)", body)
    assert "returns boolean" in body
    assert "security definer" in body
    assert re.search(r"\bstable\b", body)
    assert re.search(r"set search_path(=| to )''", body), "search_path must be pinned to the empty string"


@pytest.mark.parametrize("fn,arg", HELPERS.items())
def test_helper_privileges(sql, fn, arg):
    c = _compact(sql)
    assert re.search(rf"revoke (all|execute) on function public\.{fn}\({arg}\) ?from public", c), \
        f"{fn}: EXECUTE must be revoked from public"
    m = re.search(rf"grant execute on function public\.{fn}\({arg}\) ?to ([a-z_, ]+)", c)
    assert m, f"{fn}: GRANT EXECUTE missing"
    assert {r.strip() for r in m.group(1).split(",")} == {"anon", "authenticated"}


def test_is_administrator_logic(sql):
    body = _helper_body(_compact(sql), "is_administrator")
    assert "auth.uid()" in body
    assert "role='administrator'" in body
    assert "(auth.jwt()->>'aal')='aal2'" in body


def test_no_helper_search_path_includes_public_or_pg_temp(sql):
    assert "set search_path = public" not in sql and "pg_temp" not in sql
    assert len(re.findall(r"set search_path = ''", sql)) == 3


def test_event_is_removed_logic(sql):
    body = _helper_body(_compact(sql), "event_is_removed")
    assert "public.events" in body
    assert "removed_at is not null" in body


# ---------- policies ----------

@pytest.mark.parametrize("name,spec", POLICIES.items())
def test_policy_restrictive_and_command(sql, name, spec):
    table, cmd = spec
    stmt = _policy_stmt(sql, name)
    assert re.search(rf'create policy "{name}" on {re.escape(table)} as restrictive for {cmd}\b', stmt), stmt


CHAT_LIVE = r"removed_at is null and not public\.event_is_removed\(event_id\)"


def test_select_policy_predicates(sql):
    stmt = _compact(_policy_stmt(sql, "events_removed_select_guard"))
    assert re.search(r"using\(removed_at is null or public\.is_administrator\(\)\)", stmt), stmt
    stmt = _compact(_policy_stmt(sql, "event_chats_removed_select_guard"))
    assert re.search(rf"using\(\({CHAT_LIVE}\) ?or public\.is_administrator\(\)\)", stmt), stmt


def test_events_update_policy_predicates(sql):
    stmt = _compact(_policy_stmt(sql, "events_removed_update_guard"))
    assert re.search(r"using\(removed_at is null\)", stmt), stmt
    assert re.search(r"with check\(removed_at is null\)", stmt), stmt


def test_events_delete_policy_predicates(sql):
    stmt = _compact(_policy_stmt(sql, "events_removed_delete_guard"))
    assert re.search(r"using\(removed_at is null\)", stmt), stmt


def test_chats_update_policy_consults_parent_event(sql):
    stmt = _compact(_policy_stmt(sql, "event_chats_removed_update_guard"))
    assert re.search(rf"using\({CHAT_LIVE}\)", stmt), stmt
    # WITH CHECK also stops a message being moved into a removed event.
    assert re.search(rf"with check\({CHAT_LIVE}\)", stmt), stmt


def test_chats_delete_policy_consults_parent_event(sql):
    stmt = _compact(_policy_stmt(sql, "event_chats_removed_delete_guard"))
    assert re.search(rf"using\({CHAT_LIVE}\)", stmt), stmt


def test_chats_policies_only_use_event_is_removed_helper(sql):
    for name in ("event_chats_removed_select_guard", "event_chats_removed_update_guard",
                 "event_chats_removed_delete_guard"):
        stmt = _policy_stmt(sql, name)
        assert not re.search(r"from (public\.)?events\b", stmt), "must not subquery events directly"


# ---------- cascade-protection trigger ----------

TRIGGER_FN = "protect_removed_chats_on_event_delete"


def _trigger_fn(sql: str) -> str:
    c = _compact(sql)
    m = re.search(rf"create or replace function public\.{TRIGGER_FN}\(\)", c)
    assert m, "trigger function missing"
    end = re.search(r"\$\$;", c[m.end():])
    assert end, "trigger function body not terminated"
    return c[m.start(): m.end() + end.end()]


def test_trigger_function_definition(sql):
    body = _trigger_fn(sql)
    assert "returns trigger" in body
    assert "language plpgsql" in body
    assert "security definer" in body
    assert re.search(r"set search_path(=| to )''", body), "search_path must be pinned to the empty string"
    # direct clients only, so the service-role backend keeps working
    assert re.search(r"auth\.role\(\) ?in ?\('anon', ?'authenticated'\)", body), body
    assert "public.event_chats" in body
    assert re.search(r"c\.event_id=old\.id and c\.removed_at is not null", body), body
    assert "errcode='42501'" in body
    assert "return old" in body
    assert "is_administrator" not in body, "no admin exception"


def test_trigger_function_privileges(sql):
    c = _compact(sql)
    assert re.search(rf"revoke all on function public\.{TRIGGER_FN}\(\) ?from public", c)
    assert not re.search(rf"grant [a-z, ]+ on function public\.{TRIGGER_FN}", c)


def test_trigger_is_before_delete_on_events_and_recreated(sql):
    stmts = _statements(sql)
    creates = [i for i, s in enumerate(stmts) if re.search(r"(^| )create trigger ", s)]
    assert len(creates) == 1
    stmt = stmts[creates[0]]
    assert re.search(r"create trigger events_protect_removed_chats before delete on public\.events "
                     r"for each row execute function public\." + TRIGGER_FN + r"\(\)", stmt), stmt
    assert stmts[creates[0] - 1].endswith("drop trigger if exists events_protect_removed_chats on public.events")


def test_insert_policy_uses_helper_not_subquery(sql):
    stmt = _compact(_policy_stmt(sql, "event_chats_removed_insert_guard"))
    assert re.search(r"with check\(not \(?public\.event_is_removed\(event_id\)\)?\)", stmt), stmt
    assert "public.event_is_removed(" in stmt
    assert not re.search(r"from (public\.)?events\b", stmt), "must not subquery events directly"
    assert "select" not in stmt.split("with check", 1)[1]


def test_no_admin_exception_on_update_delete(sql):
    for s in _statements(sql):
        if "create policy" in s and re.search(r" for (update|delete)\b", s):
            assert "is_administrator" not in s, s


def test_drop_policy_precedes_every_create_policy(sql):
    stmts = _statements(sql)
    creates = [i for i, s in enumerate(stmts) if re.search(r"(^| )create policy ", s)]
    assert len(creates) == len(POLICIES), "unexpected number of CREATE POLICY statements"
    for i in creates:
        name = re.search(r'create policy "([^"]+)" on ([a-z_.]+)', stmts[i])
        assert name, stmts[i]
        expected = f'drop policy if exists "{name.group(1)}" on {name.group(2)}'
        assert i > 0 and stmts[i - 1].endswith(expected), \
            f"{name.group(1)} must be immediately preceded by: {expected}"


def test_every_policy_is_created_with_exact_names(sql):
    assert set(re.findall(r'create policy "([^"]+)"', sql)) == set(POLICIES)


# ---------- guard rails ----------

def test_baseline_policies_untouched(sql):
    for name in BASELINE_POLICIES:
        assert name.lower() not in sql, f"baseline policy {name!r} must not be referenced"
    assert "alter policy" not in sql
    for s in _statements(sql):
        if re.search(r"(^| )drop policy", s):
            assert re.search(r'"(' + "|".join(POLICIES) + r')"', s), f"unexpected DROP POLICY: {s}"


def test_no_bypass_tricks(sql):
    assert "service_role" not in sql
    assert "bypassrls" not in sql
    assert "disable row level security" not in sql
    assert "permissive" not in sql
