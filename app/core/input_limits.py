"""Server-side limits for free text that users type (FR 12.4).

These numbers are the single source of truth for the backend. The frontend
must use the same numbers on its screens; if one side changes, the other must
change with it. Lengths are counted in characters after leading and trailing
whitespace is removed, which is also how the database CHECK constraints in
supabase/migrations/20261005120000_input_validation_limits.sql count them.
"""

# Profile biography: optional, may be cleared with an empty string.
BIO_MAX_LENGTH = 500

# Event title: required, one line.
EVENT_TITLE_MIN_LENGTH = 3
EVENT_TITLE_MAX_LENGTH = 100

# Event description: optional.
EVENT_DESCRIPTION_MAX_LENGTH = 3000

# Chat message: required. This is the length of the stored `content` string.
# The frontend wraps the typed text in a small JSON envelope before sending,
# so the text box on the screen must allow fewer characters than this.
CHAT_MESSAGE_MIN_LENGTH = 1
CHAT_MESSAGE_MAX_LENGTH = 2000

# Search text sent in query strings (event search, city filter, admin search).
SEARCH_TEXT_MAX_LENGTH = 200