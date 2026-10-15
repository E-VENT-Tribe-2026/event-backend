"""Shared Pydantic field-validator helpers for username and full_name fields.

Both auth_schema.py and profile_schema.py import from here so that the
validation rules stay in one place and cannot silently diverge.
"""

import re
import unicodedata

_ALLOWED_NAME_PUNCTUATION = set(".'-,\"''\u2019()")



# Line breaks and tabs are the only control characters allowed in multi-line
# text. Everything else in the Unicode "Cc" category (NUL, escape, backspace,
# ...) is refused: PostgreSQL cannot store NUL in text columns, and the rest
# have no place in text a person typed.
_MULTILINE_ALLOWED_CONTROLS = {"\n", "\r", "\t"}


def validate_text_value(
    v,
    *,
    field_label: str,
    min_length: int = 0,
    max_length: int,
    allow_newlines: bool = True,
) -> str:
    """Validate free text a user typed and return it with outer whitespace removed.

    Rules (shared by bio, event title, event description and chat messages):
    - the value must be a string (numbers, lists and objects are refused);
    - leading and trailing whitespace is removed before anything is counted;
    - the remaining length must be within [min_length, max_length];
    - control characters are refused, except line breaks and tabs when
      ``allow_newlines`` is True.

    Raises ValueError (converted to HTTP 422 by Pydantic) on any violation.
    """
    if not isinstance(v, str):
        raise ValueError(f"{field_label} must be text.")

    stripped = v.strip()

    if len(stripped) < min_length:
        if min_length <= 1:
            raise ValueError(f"{field_label} cannot be empty or only spaces.")
        raise ValueError(
            f"{field_label} must be at least {min_length} characters "
            "once leading and trailing spaces are removed."
        )

    if len(stripped) > max_length:
        raise ValueError(f"{field_label} must be at most {max_length} characters.")

    allowed = _MULTILINE_ALLOWED_CONTROLS if allow_newlines else set()
    for c in stripped:
        if unicodedata.category(c) == "Cc" and c not in allowed:
            if c in _MULTILINE_ALLOWED_CONTROLS:
                raise ValueError(f"{field_label} must be a single line.")
            raise ValueError(f"{field_label} contains characters that are not allowed.")

    return stripped

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
