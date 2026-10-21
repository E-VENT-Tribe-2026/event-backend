import re
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parent.parent / "supabase" / "migrations"
FIX = MIGRATIONS / "20261022120000_fix_administrator_role_value.sql"


def _last_role_check_values():
    """Return the allowed role values from the last migration that defines profiles_role_check."""
    pattern = re.compile(
        r"ADD CONSTRAINT profiles_role_check CHECK \(role IN \(([^)]*)\)\)", re.IGNORECASE
    )
    allowed = None
    for path in sorted(MIGRATIONS.glob("*.sql")):
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            allowed = set(re.findall(r"'([^']+)'", match.group(1)))
    return allowed


def test_final_role_constraint_allows_administrator_only():
    assert _last_role_check_values() == {"user", "administrator"}


def test_fix_migration_converts_legacy_admin_rows():
    sql = FIX.read_text(encoding="utf-8")
    assert re.search(r"SET role = 'administrator'\s+WHERE role = 'admin'", sql)


def test_fix_migration_drops_constraint_before_converting():
    sql = FIX.read_text(encoding="utf-8")
    assert sql.index("DROP CONSTRAINT") < sql.index("SET role = 'administrator'")
    assert sql.index("SET role = 'administrator'") < sql.index("ADD CONSTRAINT")


def test_fix_migration_keeps_default_user():
    sql = FIX.read_text(encoding="utf-8")
    assert re.search(r"SET DEFAULT 'user'", sql)
