"""Ticket #230: participant lists must not show the username of a user who was made an administrator."""
from unittest.mock import MagicMock, patch

from app.services import participant_service

SVC = "app.services.participant_service"
EVENT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
ADMIN_USER = "11111111-1111-4111-8111-111111111111"
REGULAR_USER = "22222222-2222-4222-8222-222222222222"


def _profile(username, full_name, role):
    return {"username": username, "full_name": full_name, "avatar_url": "https://img/a.png",
            "avatar_kind": "photo", "icon_id": None, "role": role}


def _chain(data):
    chain = MagicMock()
    for method in ("select", "eq", "in_"):
        getattr(chain, method).return_value = chain
    chain.execute.return_value = MagicMock(data=data)
    return chain


def test_participant_query_selects_role():
    """Without role in the query, build_user_summary cannot tell the user is an administrator."""
    assert "role" in participant_service._PARTICIPANT_SELECT


@patch(f"{SVC}.supabase")
def test_promoted_admin_keeps_participation_without_username(mock_sb):
    rows = [
        {"user_id": ADMIN_USER, "status": "going", "profiles": _profile("alice", "Alice Smith", "administrator")},
        {"user_id": REGULAR_USER, "status": "going", "profiles": _profile("bob", "Bob Jones", "user")},
    ]
    chain = _chain(rows)
    mock_sb.table.return_value = chain

    result = participant_service.get_event_participants(EVENT_ID)

    # The query asks the database for the role.
    assert "role" in chain.select.call_args.args[0]

    by_id = {r["user_id"]: r for r in result}
    # The administrator's participation is still listed...
    admin = by_id[ADMIN_USER]["user"]
    # ...with full name and picture, but no username, and full name as display name.
    assert admin["username"] is None
    assert admin["display_name"] == "Alice Smith"
    assert admin["full_name"] == "Alice Smith"
    assert admin["avatar_url"] == "https://img/a.png"
    # The role itself is not exposed in the response.
    assert "role" not in by_id[ADMIN_USER]["user"]
    assert by_id[ADMIN_USER]["profiles"] == {"full_name": "Alice Smith", "avatar_url": "https://img/a.png"}

    # A regular participant is unchanged.
    assert by_id[REGULAR_USER]["user"]["username"] == "bob"
    assert by_id[REGULAR_USER]["user"]["display_name"] == "bob"


@patch(f"{SVC}.get_friend_ids", return_value=[ADMIN_USER])
@patch(f"{SVC}.is_event_hidden", return_value=False)
@patch(f"{SVC}.get_event", return_value={"id": EVENT_ID, "created_by": ADMIN_USER})
@patch(f"{SVC}.supabase")
def test_friends_attending_organizer_lookup_selects_role(mock_sb, *_):
    participants = _chain([])
    organizer = _chain([_profile("alice", "Alice Smith", "administrator")])
    mock_sb.table.side_effect = lambda name: organizer if name == "profiles" else participants

    result = participant_service.get_friends_attending(EVENT_ID, REGULAR_USER)

    assert "role" in organizer.select.call_args.args[0]
    assert result[0]["user"]["username"] is None
    assert result[0]["user"]["display_name"] == "Alice Smith"
