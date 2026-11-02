import pytest
from unittest.mock import patch

from app.core.user_rate_limit import reset_user_rate_limits
from tests._supabase_mock import make_table_router


@pytest.fixture(autouse=True)
def reset_rate_limits():
    """Tests share one mock user, so per-user request counts must not leak between tests."""
    reset_user_rate_limits()
    yield


@pytest.fixture(autouse=True)
def no_blocks_by_default():
    """Tests of other features run as if nobody has blocked anyone.

    Without this, the block checks would query the real database. Tests of blocking patch
    app.services.block_visibility.supabase themselves, which overrides this default.
    """
    mock_sb, chains = make_table_router()
    for method in ("select", "eq", "in_", "or_", "limit", "upsert"):
        getattr(chains["user_blocks"], method).return_value = chains["user_blocks"]
    chains["user_blocks"].execute.return_value.data = []
    chains["event_participants"].execute.return_value.data = []
    with patch("app.services.block_visibility.supabase", mock_sb):
        yield


@pytest.fixture(autouse=True)
def no_removed_content_by_default():
    """Tests of other features run as if no event is removed.

    Without this, the removed-content lookups would query the real database. Tests of
    removals patch app.services.removed_content.supabase themselves, which overrides this.
    """
    mock_sb, chains = make_table_router()
    chains["events"].execute.return_value.data = []
    with patch("app.services.removed_content.supabase", mock_sb):
        yield
