from unittest.mock import MagicMock


def make_table_router():
    """Builds a mock supabase client whose .table(name) routes to a
    per-table MagicMock chain that supports the fluent query builder API.
    Returns (mock_sb, chains) where chains is a dict keyed by table name.
    """
    class _Chains(dict):
        # Create a table's chain on first access, so tests can configure
        # chains["events"] before the service ever calls .table("events").
        def __missing__(self, name):
            chain = MagicMock()
            for method in ("select", "eq", "in_", "order", "range", "single", "insert", "update", "delete"):
                getattr(chain, method).return_value = chain
            self[name] = chain
            return chain

    mock_sb = MagicMock()
    chains = _Chains()
    mock_sb.table.side_effect = lambda name: chains[name]
    return mock_sb, chains
