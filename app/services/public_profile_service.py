from fastapi import HTTPException, status
from app.services.block_visibility import has_blocked
from app.services.profile_service import get_public_profile
from app.services.event_service import get_profile_events
from app.services.friendship_service import get_friendship_state

# Friendship states in which a viewer may see a private profile.
PRIVATE_PROFILE_VISIBLE_STATUSES = {"self", "friends", "request_sent", "request_received"}

# What the blocking user still sees of a profile they blocked: the top, no events or friends.
BLOCKED_PROFILE_FIELDS = (
    "id", "username", "full_name", "avatar_url", "avatar_kind", "icon_id",
    "banner_url", "bio", "interests",
)


def build_public_profile(user_id: str, viewer_id: str) -> dict:
    """
    Build a user's profile with their events and the viewer's friendship state.
    Private profiles are only visible to the owner, their friends and users
    with a pending request in either direction; others get a 403.
    A viewer the profile's owner blocked gets a 404 "profile_unavailable". The blocking user
    gets only the top of the profile, with blocked_by_me true so the screen can offer unblocking.
    """
    is_self = str(user_id).lower() == str(viewer_id).lower()

    if not is_self and has_blocked(user_id, viewer_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "profile_unavailable", "message": "This profile is unavailable."},
        )

    profile = get_public_profile(user_id)

    if not is_self and has_blocked(viewer_id, user_id):
        top = {field: profile.get(field) for field in BLOCKED_PROFILE_FIELDS}
        top["blocked_by_me"] = True
        return top

    friendship = get_friendship_state(viewer_id, user_id)

    if (
        profile.get("visibility") != "public"
        and friendship["status"] not in PRIVATE_PROFILE_VISIBLE_STATUSES
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This profile is private"
        )

    profile["events"] = get_profile_events(user_id, viewer_id)
    profile["friendship"] = friendship
    profile["blocked_by_me"] = False
    return profile
