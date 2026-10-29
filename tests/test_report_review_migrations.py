"""Migration-text tests for ticket 235 (admin Reports tab backend, Phase 1).

Test-first: the two migrations (closure columns; realtime/RLS) are discovered
by content among migrations newer than LAST_EXISTING. No DB or network.

Assertions about executable SQL run on comment-stripped text (so Rollback
comments cannot satisfy them); banner assertions run on the raw text. The
check_* functions take the raw migration text so they can be reused against
mutated copies.
"""
import re
from pathlib import Path

import pytest

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "supabase" / "migrations"
LAST_EXISTING = 20261026120000
NAME_RE = re.compile(r"^\d{14}_[a-z0-9_]+\.sql$")


def _strip_comments(text: str) -> str:
    return re.sub(r"--[^\n]*", "", text)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _sql(raw: str) -> str:
    """Executable SQL: comments stripped, lowercased, whitespace collapsed."""
    return _norm(_strip_comments(raw))


def _compact(s: str) -> str:
    """Drop spaces around parentheses and operators so formatting does not matter."""
    return re.sub(r" ?(\(|\)|=|<>|->>) ?", r"\1", s)


def _statement(t: str, needle: str) -> str:
    stmts = [s.strip() for s in t.split(";") if needle in s]
    assert len(stmts) == 1, f"expected exactly one statement containing {needle!r}, found {len(stmts)}"
    return stmts[0]


def _new_migrations():
    out = []
    for p in sorted(MIGRATIONS_DIR.glob("*.sql")):
        m = re.match(r"^(\d{14})", p.name)
        if m and int(m.group(1)) > LAST_EXISTING:
            out.append(p)
    return out


def _find(marker, label):
    for p in _new_migrations():
        raw = p.read_text(encoding="utf-8")
        if marker in _sql(raw):
            return p, raw
    pytest.fail(f"Migration {label} not found: no migration newer than {LAST_EXISTING} matches")


@pytest.fixture(scope="module")
def mig_a():
    return _find("add column if not exists closed_by", "A (closure columns on public.reports)")


@pytest.fixture(scope="module")
def mig_b():
    return _find("alter publication supabase_realtime add table public.reports",
                 "B (realtime/RLS for public.reports)")


# ---------- checks (raw text in; AssertionError out) ----------

def check_banner(raw):
    assert "235" in raw, "banner must mention ticket 235"
    assert re.search(r"deployment", raw, re.I), "banner must have a Deployment line"
    assert re.search(r"idempotent|safe to re-run", raw, re.I), "must say Idempotent / safe to re-run"
    assert re.search(r"rollback", raw, re.I), "must contain Rollback comments"


def check_a_columns(raw):
    t = _sql(raw)
    for col in ("outcome", "closed_by", "closed_at"):
        assert re.search(rf"add column if not exists {col}\b", t), f"missing 'add column if not exists {col}'"
    assert re.search(r"add column if not exists outcome text", t), "outcome must be text"
    assert re.search(r"closed_by uuid references (public\.)?profiles ?\( ?id ?\)", t), \
        "closed_by must be uuid referencing profiles(id)"
    assert re.search(r"closed_at timestamptz", t), "closed_at must be timestamptz"


def check_a_constraints(raw):
    t = _sql(raw)
    for name in ("reports_outcome_check", "reports_closure_consistent"):
        add = re.search(rf"add constraint {name}\b", t)
        assert add, f"missing 'add constraint {name}'"
        drop = re.search(rf"drop constraint if exists {name}\b", t)
        assert drop and drop.start() < add.start(), \
            f"'drop constraint if exists {name}' must precede its add constraint"


def check_a_outcome_values(raw):
    s = _statement(_sql(raw), "add constraint reports_outcome_check")
    for v in ("dismissed", "warned", "content_removed", "suspended"):
        assert f"'{v}'" in s, f"outcome value {v} missing from the outcome CHECK"


def check_a_closure(raw):
    s = _statement(_sql(raw), "add constraint reports_closure_consistent")
    assert re.search(r"status = 'open' and outcome is null and closed_by is null and closed_at is null", s), \
        "open branch must require outcome, closed_by and closed_at all null"
    assert re.search(r"status (<>|!=) 'open' and outcome is not null and closed_by is not null "
                     r"and closed_at is not null", s), \
        "closed branch must require outcome, closed_by and closed_at all not null"
    assert s.endswith("not valid"), "closure constraint must be added NOT VALID"


def check_a_status_untouched(raw):
    for stmt in _sql(raw).split(";"):
        if "add constraint" in stmt and "action_taken" in stmt:
            pytest.fail("migration must not redefine the status check (action_taken)")


def check_b_publication(raw):
    t = _sql(raw)
    assert "do $$" in t and "end $$" in t, "missing idempotent DO block"
    assert "alter publication supabase_realtime add table public.reports" in t
    assert "pg_publication" in t and "pg_publication_tables" in t, "guards must use pg_publication(_tables)"
    assert "alter table public.reports replica identity full" in t


def check_b_rls_and_policy(raw):
    t = _sql(raw)
    rls = t.find("alter table public.reports enable row level security")
    assert rls >= 0, "RLS must be enabled on public.reports"
    assert len(re.findall(r"\bcreate policy\b", t)) == 1, "expected exactly one create policy"
    assert rls < t.find("create policy"), "enable RLS must come before create policy"
    assert "drop policy if exists reports_select_admin" in t, "missing executable idempotent drop policy"
    m = re.search(r"create policy reports_select_admin on public\.reports for select to authenticated "
                  r"using \((.*)\)$", _statement(t, "create policy"))
    assert m, "policy must be reports_select_admin ON public.reports FOR SELECT TO authenticated USING (...)"
    body = _compact(m.group(1)).strip()
    assert re.fullmatch(r"exists\(select 1 from (public\.)?profiles p where p\.id=auth\.uid\(\)"
                        r"and p\.role='administrator'\)and\(auth\.jwt\(\)->>'aal'\)='aal2'", body), \
        f"USING must be exists(admin profile lookup) AND (auth.jwt() ->> 'aal') = 'aal2', got: {body}"
    assert not re.search(r"\bor\b", body), "policy must not contain OR (aal2 must be required)"


def check_b_grants(raw):
    t = _sql(raw)
    assert re.search(r"grant select on public\.reports to authenticated\b", t)
    grants = [g.strip() for g in re.findall(r"\bgrant\b[^;]*", t) if "public.reports" in g]
    assert grants, "grant on public.reports missing"
    for g in grants:
        assert re.fullmatch(r"grant select on (table )?public\.reports to authenticated", g), \
            f"only 'grant select ... to authenticated' is allowed on public.reports, got: {g}"
    assert not re.search(r"\bto (anon|public)\b", t), "must not grant/target anon or public"


def check_mig_a(raw):
    for chk in (check_banner, check_a_columns, check_a_constraints, check_a_outcome_values,
                check_a_closure, check_a_status_untouched):
        chk(raw)


def check_mig_b(raw):
    for chk in (check_banner, check_b_publication, check_b_rls_and_policy, check_b_grants):
        chk(raw)


# ---------- naming / ordering ----------

def test_migration_names_and_timestamps(mig_a, mig_b):
    for p, _ in (mig_a, mig_b):
        assert NAME_RE.match(p.name), f"bad file name: {p.name}"
        assert int(p.name[:14]) > LAST_EXISTING, f"{p.name} not newer than {LAST_EXISTING}"
    assert mig_a[0] != mig_b[0], "A and B must be separate migrations"


# ---------- Migration A ----------

def test_a_columns_added_idempotently(mig_a):
    check_a_columns(mig_a[1])


def test_a_constraints_named_and_dropped_first(mig_a):
    check_a_constraints(mig_a[1])


def test_a_outcome_check_values(mig_a):
    check_a_outcome_values(mig_a[1])


def test_a_closure_consistency_constraint(mig_a):
    check_a_closure(mig_a[1])


def test_a_does_not_redefine_status_check(mig_a):
    check_a_status_untouched(mig_a[1])


def test_a_banner(mig_a):
    check_banner(mig_a[1])


# ---------- Migration B ----------

def test_b_publication_and_replica_identity(mig_b):
    check_b_publication(mig_b[1])


def test_b_rls_and_select_policy(mig_b):
    check_b_rls_and_policy(mig_b[1])


def test_b_grants(mig_b):
    check_b_grants(mig_b[1])


def test_b_banner(mig_b):
    check_banner(mig_b[1])


# ---------- Migration C: lookup indexes (report history, closed count) ----------

REALTIME_MIGRATION_TS = 20261027130000
INDEXES = {
    "reports_reporter_created_idx": r"\(reporter_id, created_at desc\) where reporter_id is not null",
    "reports_reported_user_idx": r"\(reported_user_id\) where reported_user_id is not null",
    "reports_event_idx": r"\(event_id\) where event_id is not null",
    "reports_closed_by_idx": r"\(closed_by\) where closed_by is not null",
}


@pytest.fixture(scope="module")
def mig_c():
    return _find("reports_closed_by_idx", "C (lookup indexes on public.reports)")


def check_c_indexes(raw):
    t = _sql(raw)
    for name, tail in INDEXES.items():
        assert re.search(rf"create index if not exists {name} on public\.reports {tail}(;|$)", t), \
            f"missing 'create index if not exists {name} on public.reports ...' with the expected columns/predicate"


def check_c_rollback(raw):
    comments = "\n".join(re.findall(r"--[^\n]*", raw)).lower()
    for name in INDEXES:
        assert re.search(rf"drop index if exists (public\.)?{name}\s*;", comments), \
            f"Rollback comments must contain 'drop index if exists {name};'"


def check_c_only_creates_indexes(raw):
    stmts = [s.strip() for s in _sql(raw).split(";") if s.strip()]
    assert len(stmts) == len(INDEXES), f"expected exactly {len(INDEXES)} statements, got {len(stmts)}"
    for s in stmts:
        assert s.startswith("create index if not exists "), f"only 'create index if not exists' is allowed: {s}"


def check_mig_c(raw):
    for chk in (check_banner, check_c_indexes, check_c_rollback, check_c_only_creates_indexes):
        chk(raw)


def test_c_name_and_timestamp(mig_c):
    p, _ = mig_c
    assert NAME_RE.match(p.name), f"bad file name: {p.name}"
    assert int(p.name[:14]) > REALTIME_MIGRATION_TS, f"{p.name} must come after the realtime migration"


def test_c_banner_and_deployment_note(mig_c):
    raw = mig_c[1]
    check_banner(raw)
    assert "20261027120000_report_closure_columns.sql" in raw, "banner must name the migration it needs first"
    assert "closed_by" in raw


def test_c_creates_all_four_indexes_idempotently(mig_c):
    check_c_indexes(mig_c[1])


def test_c_rollback_drops_every_index(mig_c):
    check_c_rollback(mig_c[1])


def test_c_executable_sql_only_creates_indexes(mig_c):
    check_c_only_creates_indexes(mig_c[1])


def test_c_does_not_change_which_files_a_and_b_are_found_in(mig_a, mig_b, mig_c):
    assert mig_a[0].name == "20261027120000_report_closure_columns.sql"
    assert mig_b[0].name == "20261027130000_reports_realtime_admin.sql"
    assert len({mig_a[0], mig_b[0], mig_c[0]}) == 3
    check_mig_a(mig_a[1])
    check_mig_b(mig_b[1])
    check_mig_c(mig_c[1])
    # the other migrations' markers must not occur in C, nor C's marker in A or B
    assert "reports_closed_by_idx" not in _sql(mig_a[1]) and "reports_closed_by_idx" not in _sql(mig_b[1])
    assert "add column if not exists closed_by" not in _sql(mig_c[1])
    assert "alter publication supabase_realtime add table public.reports" not in _sql(mig_c[1])
