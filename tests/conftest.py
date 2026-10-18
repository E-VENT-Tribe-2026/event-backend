import pytest
from unittest.mock import patch

from tests._supabase_mock import make_table_router


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
