from fastapi import HTTPException, status
from app.services.profile_service import get_public_profile
from app.services.event_service import get_profile_events
from app.services.friendship_service import get_friendship_state

# Friendship states in which a viewer may see a private profile.
PRIVATE_PROFILE_VISIBLE_STATUSES = {"self", "friends", "request_sent", "request_received"}


def build_public_profile(user_id: str, viewer_id: str) -> dict:
    """
    Build a user's profile with their events and the viewer's friendship state.
    Private profiles are only visible to the owner, their friends and users
    with a pending request in either direction; others get a 403.
    """
    profile = get_public_profile(user_id)
    friendship = get_friendship_state(viewer_id, user_id)

    if (
        profile.get("visibility") != "public"
        and friendship["status"] not in PRIVATE_PROFILE_VISIBLE_STATUSES
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This profile is private"
        )

    profile["events"] = get_profile_events(user_id)
    profile["friendship"] = friendship
    return profile
