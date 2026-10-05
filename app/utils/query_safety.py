"""Helpers that keep user input from changing the shape of a database query (FR 12.4).

How queries are built in this backend
-------------------------------------
All database access goes through the Supabase/PostgREST client. Values passed
to .eq(), .ilike(), .insert(), .update() and .rpc() are sent as separate,
URL-encoded parameters or as a JSON body; PostgREST binds them as values, so
they can never become SQL. Two things still need care:

1. LIKE/ILIKE patterns. Inside a pattern, ``%`` and ``_`` are wildcards and
   ``\\`` is the escape character; PostgREST also turns ``*`` into ``%``. If a
   search term is pasted into ``f"%{term}%"`` unescaped, a user can change what
   the pattern matches (for example ``%`` returns every row). ``like_contains``
   builds a "contains" pattern in which the term only ever matches literally.

2. Hand-built filter strings for .or_() and .in_(). Commas, dots and brackets
   in a value would add or change conditions. Only use these with values that
   have been validated to a strict shape first (see ``_uuid`` in
   friendship_service), never with free text.
"""


def escape_like(value: str) -> str:
    """Escape LIKE wildcards so user input is matched literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def like_contains(term: str) -> str | None:
    """Return an ILIKE pattern matching rows that contain ``term`` literally.

    Leading/trailing whitespace is removed and ``*`` is dropped, because
    PostgREST treats ``*`` as a wildcard and it cannot be escaped there.
    Returns None when nothing is left to search for; callers should then skip
    the filter (or return an empty result) instead of matching everything.
    """
    cleaned = term.strip().replace("*", "")
    if not cleaned:
        return None
    return f"%{escape_like(cleaned)}%"