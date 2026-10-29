from app.db.supabase_client import supabase
from app.services.removed_content import LOOKUP_CHUNK

_ENTRY_COLUMNS = "id, status, created_at, target_type, reason"

# Rows requested per page. PostgREST caps a response at max_rows (1000 locally, possibly less when
# hosted), so every lookup is read in pages until it is complete.
PAGE_SIZE = 1000


def _read_all(build) -> list:
    """All rows of a query, read page by page.

    `build()` returns a fresh select(..., count="exact") query that is already ordered in the database,
    so pages never overlap or skip rows. Stops on an empty page or once the exact total is collected;
    a short page is NOT a stop signal (the server may cap a page below PAGE_SIZE).
    """
    rows = []
    while True:
        res = build().range(len(rows), len(rows) + PAGE_SIZE - 1).execute()
        page = res.data or []
        if not page:
            return rows
        rows.extend(page)
        if res.count is not None and len(rows) >= res.count:
            return rows


def _entry(row: dict) -> dict:
    return {
        "id": row["id"],
        "status": row["status"],
        "created_at": str(row["created_at"]),
        "target_type": row["target_type"],
        "reason": row["reason"],
    }


def _newest_first(entries) -> list:
    """Newest first; reports filed in the same instant: highest (numeric) id first."""
    return sorted(entries, key=lambda e: (e["created_at"], e["id"]), reverse=True)


def _reports(columns: str):
    """A fresh reports select with an exact count, newest first with a stable id tiebreak."""
    return supabase.table("reports").select(columns, count="exact").order("created_at", desc=True).order("id", desc=True)


def _reports_about(user_id: str) -> list:
    """User and message reports about the user, plus event reports about the events they organize."""
    about = {}
    for row in _read_all(lambda: _reports(_ENTRY_COLUMNS).eq("reported_user_id", user_id)):
        about[row["id"]] = {**_entry(row), "event": None}

    events = _read_all(
        lambda: supabase.table("events").select("id, title", count="exact").eq("created_by", user_id).order("id")
    )
    titles = {ev["id"]: ev.get("title") or "" for ev in events}
    ids = list(titles)
    for start in range(0, len(ids), LOOKUP_CHUNK):
        chunk = ids[start:start + LOOKUP_CHUNK]
        rows = _read_all(
            lambda: _reports(_ENTRY_COLUMNS + ", event_id").eq("target_type", "event").in_("event_id", chunk)
        )
        for row in rows:
            about[row["id"]] = {**_entry(row),
                                "event": {"id": row["event_id"], "title": titles[row["event_id"]]}}
    return _newest_first(about.values())


def _reports_made(user_id: str) -> list:
    rows = _read_all(lambda: _reports(_ENTRY_COLUMNS).eq("reporter_id", user_id))
    return _newest_first(_entry(row) for row in rows)


def report_history(user_id: str) -> dict:
    """Reports about a regular user (themselves or events they organize) and reports they filed."""
    return {"about": _reports_about(user_id), "made": _reports_made(user_id)}


def reports_closed(admin_id: str) -> int:
    """How many reports this administrator closed (dismissed or acted on)."""
    # limit(1): only the exact count header is wanted, not up to max_rows id rows.
    res = supabase.table("reports").select("id", count="exact").eq("closed_by", admin_id).limit(1).execute()
    if res.count is not None:
        return res.count
    return len(_read_all(lambda: supabase.table("reports").select("id", count="exact")
                         .eq("closed_by", admin_id).order("id")))
