"""Shared Pydantic field-validator helpers for username and full_name fields.

Both auth_schema.py and profile_schema.py import from here so that the
validation rules stay in one place and cannot silently diverge.
"""

import re

_ALLOWED_NAME_PUNCTUATION = set(".'-,\"''\u2019()")


def validate_username_value(v: str) -> str:
    """Validate a username string and return the normalised (lowercase) value.

    Raises ValueError (converted to HTTP 422 by Pydantic) when the value
    does not meet the username rules.
    """
    normalized = str(v).lower()
    if not re.fullmatch(r"[a-z0-9._]{3,20}", normalized):
        raise ValueError(
            "Username must be between 3 and 20 characters and contain only lowercase "
            "letters, digits, underscores, and full stops."
        )
    return normalized


def validate_full_name_value(v: str) -> str:
    """Validate a full-name string and return the stripped value.

    Leading and trailing whitespace (including newlines) is stripped before
    validation. This is intentional normalisation — ``"John Doe\\n"`` is
    stored as ``"John Doe"`` — consistent with how name fields are handled
    in other parts of the application.  This differs from the username
    validator, which rejects trailing whitespace outright, because a trailing
    newline in a name is almost always a copy-paste artefact rather than an
    attempt to bypass validation.

    Raises ValueError (converted to HTTP 422 by Pydantic) when the value
    does not meet the full-name rules after stripping.
    """
    stripped = str(v).strip()
    if not stripped:
        raise ValueError("Full name is required and cannot be empty or only spaces.")
    if not (3 <= len(stripped) <= 50):
        raise ValueError(
            "Full name must be between 3 and 50 characters once leading and trailing "
            "spaces are removed."
        )
    if not any(c.isalpha() for c in stripped):
        raise ValueError("Full name must contain at least one letter.")
    for c in stripped:
        if not (c.isalpha() or c == " " or c in _ALLOWED_NAME_PUNCTUATION):
            raise ValueError(
                "Full name must contain only letters, spaces, and common punctuation."
            )
    return stripped
