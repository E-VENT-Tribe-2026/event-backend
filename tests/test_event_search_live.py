"""Search the configured Supabase database without adding rows.

Prints events that are already stored, then a search for a term that is not.
Blocked in the default suite because CI has no reachable database.
"""

import pytest

from app.services.event_search_service import search_events


pytestmark = pytest.mark.skip(reason="Live database test is blocked in CI")

_ABSENT_QUERY = "this-term-is-not-in-the-database"


def _print_report(title: str, result: dict) -> None:
    pagination = result["pagination"]
    more = "yes" if pagination["has_next"] else "no"
    lines = [
        "",
        title,
        f"  Success: {'yes' if result['success'] else 'no'}",
        (
            f"  Page {pagination['page']}, "
            f"showing {len(result['events'])} of {pagination['total']}, "
            f"another page: {more}"
        ),
    ]
    error = result["error"]
    if error:
        field = f" ({error['field']})" if error.get("field") else ""
        lines.append(f"  Error: {error['code']}{field} — {error['message']}")
    if not result["events"]:
        lines.append("  No events.")
    for number, event in enumerate(result["events"], start=1):
        cost = "not set" if event["cost"] is None else f"{event['cost']:g}"
        capacity = "not set" if event["max_capacity"] is None else str(event["max_capacity"])
        lines.extend(
            [
                f"  {number}. {event['title']}",
                f"     When: {event['start_datetime']} to {event['end_datetime']}",
                f"     Where: {event['location_name'] or 'not set'}",
                f"     Category: {event['category'] or 'not set'}",
                f"     Cost: {cost}    Capacity: {capacity}    Status: {event['status']}",
            ]
        )
    print("\n".join(lines))


def _assert_page(result: dict, page: int, limit: int) -> None:
    assert result["success"] is True, result["error"]
    pagination = result["pagination"]
    assert pagination["page"] == page
    assert pagination["limit"] == limit
    assert 0 <= len(result["events"]) <= limit
    assert pagination["has_next"] is (page * limit < pagination["total"])
    ordered = [(event["start_datetime"], event["id"]) for event in result["events"]]
    assert ordered == sorted(ordered)


def test_search_reads_events_already_in_the_database(capsys):
    catalog = search_events({"page": 1, "limit": 10})
    with capsys.disabled():
        _print_report("Upcoming events already in the database", catalog)
    _assert_page(catalog, page=1, limit=10)

    if catalog["pagination"]["total"] > 1:
        first_page = search_events({"page": 1, "limit": 1})
        with capsys.disabled():
            _print_report("First of those events, one per page", first_page)
        _assert_page(first_page, page=1, limit=1)
        assert first_page["pagination"]["total"] == catalog["pagination"]["total"]
        assert first_page["events"][0]["id"] == catalog["events"][0]["id"]

    missing = search_events({"query": _ABSENT_QUERY, "page": 1, "limit": 10})
    with capsys.disabled():
        _print_report(f"Search for {_ABSENT_QUERY!r}", missing)
    _assert_page(missing, page=1, limit=10)
    assert missing["events"] == []
    assert missing["pagination"]["total"] == 0
    assert missing["error"] is None
