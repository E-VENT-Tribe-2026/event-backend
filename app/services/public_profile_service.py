from fastapi import HTTPException, status
from app.services.block_visibility import has_blocked
from app.services.profile_service import get_public_profile
from app.services.event_service import get_profile_events
from app.services.friendship_service import get_friendship_state, get_user_friends_summary_page

# Friendship states in which a viewer may see a private profile.
PRIVATE_PROFILE_VISIBLE_STATUSES = {"self", "friends", "request_sent", "request_received"}

# What the blocking user still sees of a profile they blocked: the top, no events or friends.
BLOCKED_PROFILE_FIELDS = (
    "id", "username", "full_name", "avatar_url", "avatar_kind", "icon_id",
    "banner_url", "bio", "interests",
)

# What a non-friend sees of a friends-only profile: username, full name, profile picture and banner only.
FRIENDS_ONLY_NON_FRIEND_FIELDS = (
    "id", "username", "full_name", "avatar_url", "avatar_kind", "icon_id",
    "banner_url", "banner", "visibility",
)


def build_public_profile(user_id: str, viewer_id: str) -> dict:
    """
    Build a user's profile with their events, friends list, and the viewer's friendship state.
    
    A public profile seen by a friend: username, full name, profile picture, banner, bio, interests,
    friends list, upcoming events and past events.
    A public profile seen by someone who is not a friend: username, full name, profile picture, banner,
    bio, interests, friends list and past events, and no upcoming events.
    A friends-only profile seen by a friend: username, full name, profile picture, banner, bio,
    interests, friends list, upcoming events and past events.
    A friends-only profile seen by someone who is not a friend: username, full name, profile picture
    and banner only.
    Cancelled events and favourites are never returned.
    """
    is_self = str(user_id).lower() == str(viewer_id).lower()

    if not is_self and has_blocked(user_id, viewer_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "profile_unavailable", "message": "This profile is unavailable."},
        )

       # Administrator and suspended accounts (#192) shall not appear to users; answer that profile is unavailable
    try:
        from app.db.supabase_client import supabase
        role_resp = supabase.table("profiles").select("role, suspended_at").eq("id", user_id).limit(1).execute()
        row = role_resp.data[0] if role_resp.data else {}
        if (row.get("role") or "").lower() in ("administrator", "admin") or (row.get("suspended_at") and not is_self):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "profile_unavailable", "message": "This profile is unavailable."},
            )
    except HTTPException:
        raise
    except Exception:
        pass

    profile = get_public_profile(user_id)
    if (profile.get("role") or "").lower() in ("administrator", "admin"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "profile_unavailable", "message": "This profile is unavailable."},
        )

    if not is_self and has_blocked(viewer_id, user_id):
        top = {field: profile.get(field) for field in BLOCKED_PROFILE_FIELDS if field in profile}
        top["blocked_by_me"] = True
        return top

    friendship = get_friendship_state(viewer_id, user_id)
    is_friend = is_self or (friendship.get("status") == "friends")

    # Legacy private profile check
    if (
        profile.get("visibility") == "private"
        and friendship.get("status") not in PRIVATE_PROFILE_VISIBLE_STATUSES
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This profile is private"
        )

    # Friends-only profile seen by someone who is not a friend
    if profile.get("visibility") == "friends_only" and not is_friend:
        restricted = {field: profile.get(field) for field in FRIENDS_ONLY_NON_FRIEND_FIELDS if field in profile}
        restricted["friendship"] = friendship
        restricted["blocked_by_me"] = False
        return restricted

    # Public profile or friends-only seen by friend
    events = get_profile_events(user_id, viewer_id)
    if not is_friend:
        # Public profile seen by someone who is not a friend: no upcoming events
        events.get("organized", {})["upcoming"] = []
        events.get("joined", {})["upcoming"] = []

    profile["events"] = events

    # Friends list
    friends_page = get_user_friends_summary_page(user_id, page=1, limit=10, viewer_id=viewer_id)
    profile["friends"] = friends_page.get("data", [])

    profile["friendship"] = friendship
    profile["blocked_by_me"] = False
    return profile
