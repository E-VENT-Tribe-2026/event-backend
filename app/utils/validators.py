import re
from fastapi import HTTPException, status

ALLOWED_NAME_PUNCTUATION = set(".'-,\"'’()")


def validate_username(username: str | None) -> str:
    """
    Validates that a username is present, converts uppercase letters to lowercase,
    and ensures it consists only of lowercase English letters, digits, underscores,
    and full stops, between 3 and 20 characters long with no spaces.
    """
    if username is None or not str(username).strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username is required."
        )

    # Convert capital letters in submitted username to lowercase
    normalized = str(username).lower()

    if not re.match(r"^[a-z0-9._]{3,20}$", normalized):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username must be between 3 and 20 characters and contain only lowercase letters, digits, underscores, and full stops with no spaces."
        )

    return normalized


def validate_full_name(full_name: str | None) -> str:
    """
    Validates that a full name is present, non-empty, between 3 and 50 characters
    once leading and trailing spaces are removed, and contains only letters, spaces,
    and common punctuation. Preserves case ('stored as typed').
    """
    if full_name is None or not str(full_name).strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Full name is required and cannot be empty or only spaces."
        )

    stripped = str(full_name).strip()

    if not (3 <= len(stripped) <= 50):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Full name must be between 3 and 50 characters once leading and trailing spaces are removed."
        )

    if not any(c.isalpha() for c in stripped):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Full name must contain at least one letter."
        )

    for c in stripped:
        if not (c.isalpha() or c == ' ' or c in ALLOWED_NAME_PUNCTUATION):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Full name must contain only letters, spaces, and common punctuation."
            )

    return stripped
