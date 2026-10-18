from fastapi import HTTPException, status
from app.services.profile_service import get_public_profile
from app.services.event_service import get_profile_events
from app.services.friendship_service import get_friendship_state, get_profile_friends

# Friendship states in which a viewer may see a private profile.
PRIVATE_PROFILE_VISIBLE_STATUSES = {"self", "friends", "request_sent", "request_received"}


def build_public_profile(user_id: str, viewer_id: str) -> dict:
    """
    Build a user's profile with their events, friends list, and the viewer's friendship state.
    
    Privacy rules:
    - Public seen by friend: all details, friends list, upcoming and past events.
    - Public seen by non-friend: all details, friends list, past events (no upcoming events).
    - Friends-only seen by friend: all details, friends list, upcoming and past events.
    - Friends-only seen by non-friend: username, full name, profile picture, banner only.
    - Private: only visible to self/friends/pending requests (403 otherwise).
    """
    profile = get_public_profile(user_id)
    friendship = get_friendship_state(viewer_id, user_id)
    visibility = str(profile.get("visibility") or "public").strip().lower()

    is_friend = friendship.get("status") in ("self", "friends")
    is_friends_only = visibility in ("friends_only", "friends only")

    # Legacy private profile check
    if (
        visibility == "private"
        and friendship.get("status") not in PRIVATE_PROFILE_VISIBLE_STATUSES
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This profile is private"
        )

    # Friends-only profile seen by someone who is not a friend:
    # return username, full name, profile picture and banner only.
    if is_friends_only and not is_friend:
        banner = profile.get("banner") or profile.get("banner_url")
        return {
            "id": profile.get("id"),
            "username": profile.get("username"),
            "full_name": profile.get("full_name"),
            "avatar_url": profile.get("avatar_url"),
            "avatar_kind": profile.get("avatar_kind") or "icon",
            "icon_id": profile.get("icon_id"),
            "banner": banner,
            "banner_url": banner,
            "visibility": profile.get("visibility"),
            "friendship": friendship,
        }

    events = get_profile_events(user_id)
    # A user's upcoming events are shown only to their friends, whatever the setting
    if not is_friend and isinstance(events, dict):
        events = {
            "organized": {
                "upcoming": [],
                "past": events.get("organized", {}).get("past", []),
            },
            "joined": {
                "upcoming": [],
                "past": events.get("joined", {}).get("past", []),
            },
        }

    if "banner_url" in profile and "banner" not in profile:
        profile["banner"] = profile.get("banner_url")
    elif "banner" in profile and "banner_url" not in profile:
        profile["banner_url"] = profile.get("banner")

    profile["events"] = events
    profile["friendship"] = friendship
    profile["friends"] = get_profile_friends(user_id)
    return profile
