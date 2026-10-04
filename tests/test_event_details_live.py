"""Read one existing event through the details tool and print it.

Does not insert rows. Blocked in the default suite because CI has no reachable database.
"""

from uuid import uuid4

import pytest

from app.db.supabase_client import supabase
from app.services.event_details_service import get_event_details
from app.services.event_search_service import search_events


pytestmark = pytest.mark.skip(reason="Live database test is blocked in CI")


def _print_report(title: str, result: dict) -> None:
    lines = [
        "",
        title,
        f"  Success: {'yes' if result['success'] else 'no'}",
    ]
    error = result["error"]
    if error:
        field = f" ({error['field']})" if error.get("field") else ""
        lines.append(f"  Error: {error['code']}{field} — {error['message']}")
    event = result["event"]
    if event is None:
        lines.append("  No event.")
    else:
        cost = "not set" if event["cost"] is None else f"{event['cost']:g}"
        capacity = "not set" if event["max_capacity"] is None else str(event["max_capacity"])
        if event["latitude"] is None or event["longitude"] is None:
            coordinates = "not set"
        else:
            coordinates = f"{event['latitude']:g}, {event['longitude']:g}"
        lines.extend(
            [
                f"  Title: {event['title']}",
                f"  When: {event['start_datetime']} to {event['end_datetime']}",
                f"  Where: {event['location_name'] or 'not set'}",
                f"  Category: {event['category'] or 'not set'}",
                f"  Cost: {cost}    Capacity: {capacity}    Status: {event['status']}",
                f"  Coordinates: {coordinates}",
                f"  Created by: {event['created_by'] or 'not set'}",
                f"  Description: {event['description'] or 'not set'}",
            ]
        )
    print("\n".join(lines))


def _user_id() -> str:
    profiles = supabase.table("profiles").select("id").limit(1).execute()
    assert profiles.data, "A profile is required so details can run as a signed-in user"
    return profiles.data[0]["id"]


def test_event_details_reads_an_existing_event(capsys):
    user_id = _user_id()
    catalog = search_events({"page": 1, "limit": 1})
    assert catalog["success"] is True, catalog["error"]

    if catalog["events"]:
        event_id = catalog["events"][0]["id"]
        found = get_event_details({"event_id": event_id}, user_id)
        with capsys.disabled():
            _print_report("Details for an event already in the database", found)
        assert found["success"] is True, found["error"]
        assert found["event"]["id"] == event_id
        assert found["event"]["status"] == "active"
    else:
        with capsys.disabled():
            print("\nNo upcoming event is stored, so there is no details record to print.")

    missing = get_event_details({"event_id": str(uuid4())}, user_id)
    with capsys.disabled():
        _print_report("Event id that is not in the database", missing)
    assert missing["success"] is False
    assert missing["event"] is None
    assert missing["error"]["code"] == "NOT_FOUND"
