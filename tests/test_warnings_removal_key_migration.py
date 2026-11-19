"""Migration-text tests for ticket #255 (content removal reuses an existing warning).

The migration adds warnings.removal_key and a partial unique index. No DB or network:
the file is located by its exact name.
Executable-SQL assertions run on comment-stripped text; banner/rollback assertions on the raw text.
"""
import re
from pathlib import Path

import pytest

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "supabase" / "migrations"
NAME = "20261113120000_warnings_removal_key.sql"
NAME_RE = re.compile(r"^\d{14}_[a-z0-9_]+\.sql$")
DEPENDENCIES = ["20261021160000_warnings_and_audit_log.sql", "20261104150000_report_assignment.sql"]


def _strip_comments(text: str) -> str:
    return re.sub(r"--[^\n]*", "", text)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _sql(raw: str) -> str:
    """Executable SQL: comments stripped, lowercased, whitespace collapsed."""
    return _norm(_strip_comments(raw))


def _compact(s: str) -> str:
    return re.sub(r" ?(\(|\)|,) ?", r"\1", s)


def _banner(raw: str) -> str:
    """The leading comment block."""
    lines = []
    for line in raw.splitlines():
        if line.strip().startswith("--") or not line.strip():
            lines.append(line)
        else:
            break
    return "\n".join(lines)


def _preflight_section(raw: str) -> str:
    """Comment text from the 'Pre-flight' marker up to the next empty comment line or non-comment line."""
    lines = raw.splitlines()
    start = next(i for i, ln in enumerate(lines)
                 if ln.strip().startswith("--") and re.search(r"pre-?flight", ln, re.I))
    out = []
    for ln in lines[start:]:
        body = ln.strip()
        if not body.startswith("--") or not body.lstrip("- ").strip():
            break
        out.append(body.lstrip("-").strip())
    return re.sub(r"\s+", " ", " ".join(out)).lower()


@pytest.fixture(scope="module")
def migration():
    path = MIGRATIONS_DIR / NAME
    if not path.is_file():
        pytest.fail(f"Migration {NAME} not found in {MIGRATIONS_DIR}")
    return path, path.read_text(encoding="utf-8")


def test_name_and_order(migration):
    path, _ = migration
    assert NAME_RE.match(path.name), f"bad file name: {path.name}"
    for dep in DEPENDENCIES:
        assert (MIGRATIONS_DIR / dep).is_file(), f"dependency {dep} does not exist"
        assert path.name > dep, f"{path.name} must sort after {dep}"


def test_adds_the_column_idempotently(migration):
    t = _sql(migration[1])
    assert re.search(r"alter table (if exists )?public\.warnings add column if not exists removal_key text(;|,| |$)", t), \
        "expected 'alter table public.warnings add column if not exists removal_key text'"
    assert not re.search(r"removal_key text (not null|default)", t), "removal_key must be a plain nullable text column"


def test_creates_the_partial_unique_index(migration):
    t = _compact(_sql(migration[1]))
    assert re.search(
        r"create unique index if not exists warnings_user_removal_key_uidx on public\.warnings"
        r"(?: using btree)?\(user_id,removal_key\) ?where removal_key is not null(;|$)", t), \
        "expected a partial UNIQUE index warnings_user_removal_key_uidx on public.warnings (user_id, removal_key) " \
        "WHERE removal_key IS NOT NULL"


def test_banner(migration):
    banner = _banner(migration[1])
    low = banner.lower()
    assert "Ticket #255" in banner
    assert "content removal reuses an existing warning" in low
    assert re.search(r"before\s+deploying\s+(the\s+)?(code|backend|application)|"
                     r"before\s+the\s+(code|backend|application)\s+is\s+deployed|"
                     r"applied\s+before\s+(the\s+)?(code|deploy)", low), \
        "banner must say the migration is applied BEFORE deploying the code"
    assert re.search(r"not\s+backfill|no\s+backfill|without\s+(a\s+)?backfill", low), \
        "banner must say existing warnings are not backfilled"
    assert re.search(r"idempotent|safe to re-run", low), "banner must say idempotent / safe to re-run"


def test_banner_has_a_read_only_preflight_query(migration):
    comments = "\n".join(re.findall(r"--[^\n]*", migration[1])).lower()
    assert re.search(r"pre-?flight", comments), "comments must have a pre-flight section"
    flat = re.sub(r"\s*--\s*", " ", comments)
    flat = re.sub(r"\s+", " ", flat)
    assert re.search(r"select [^;]*from information_schema\.columns[^;]*warnings", flat) or \
        re.search(r"select [^;]*from pg_indexes[^;]*warnings", flat), \
        "pre-flight must be a select from information_schema.columns or pg_indexes for public.warnings"
    section = _preflight_section(migration[1])
    assert re.search(r"select [^;]*from information_schema\.columns[^;]*warnings", section)
    assert re.search(r"select [^;]*from pg_indexes[^;]*warnings", section)
    assert not re.search(r"\b(update|insert|delete|drop|alter)\b", section), \
        "pre-flight section must be read-only"


def test_commented_emergency_rollback_drops_index_before_column(migration):
    raw = migration[1]
    comments = "\n".join(re.findall(r"--[^\n]*", raw)).lower()
    assert "emergency" in comments and "rollback" in comments
    drop_index = re.search(r"drop index if exists (public\.)?warnings_user_removal_key_uidx\s*;", comments)
    drop_column = re.search(r"alter table public\.warnings drop column if exists removal_key\s*;", comments)
    assert drop_index and drop_column and drop_index.start() < drop_column.start(), \
        "rollback comments must drop the index first, then the column"
    assert re.search(r"roll\s*back[^\n]*(code|application|backend)|(code|application|backend)[^\n]*roll\s*back", comments), \
        "rollback must warn that code using the column has to be rolled back first"
    assert "drop" not in _sql(raw), "rollback must be comments only: no executable DROP"


def test_only_idempotent_schema_statements_and_no_backfill(migration):
    t = _sql(migration[1])
    assert not re.search(r"\b(update|insert|delete)\b", t), "no UPDATE/INSERT/DELETE (no backfill)"
    stmts = [s.strip() for s in t.split(";") if s.strip()]
    assert len(stmts) == 2, f"expected exactly 2 statements (column, index), got {len(stmts)}"
    assert stmts[0].startswith("alter table") and "add column if not exists" in stmts[0]
    assert stmts[1].startswith("create unique index if not exists")
