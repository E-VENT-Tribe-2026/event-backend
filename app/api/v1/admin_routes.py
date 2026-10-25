import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Path
from pydantic import EmailStr
from app.core.dependencies import require_admin
from app.core.input_limits import SEARCH_TEXT_MAX_LENGTH
from app.schemas.admin_schema import (
    AdminAccountResponse,
    AdminCountsResponse,
    AdminUserListResponse,
    AdminUserDetailResponse,
    AdminEventListResponse,
    AdminEventDetailResponse,
    GrantAdminRoleResponse,
    AdminUserListCounters,
    SendRegistrationInviteResponse,
)
from app.services.admin_service import (
    get_admin_account_details,
    get_admin_counts,
    get_user_list_counters,
    list_admin_users,
    list_admin_events,
    get_admin_user_details,
    get_admin_event_details,
    grant_admin_role,
)
from app.schemas.warning_schema import (
    GiveWarningRequest,
    WarningHistoryItem,
    WarningHistoryResponse,
    AuditLogResponse,
)
from app.services.warning_service import give_warning, withdraw_warning, get_warning_history
from app.services.audit_service import list_audit_log
from app.schemas.suspension_schema import SuspensionReasonRequest, SuspensionResponse
from app.services.suspension_service import suspend_user, lift_suspension
from app.services.registration_invite_service import send_registration_invite

logger = logging.getLogger(__name__)

router = APIRouter()


def _slash(path: str, methods: list[str], **kwargs):
    """Register a trailing-slash twin so CORS does not drop the MFA token."""
    def deco(fn):
        slash_path = path if path.endswith("/") else f"{path}/"
        router.add_api_route(
            slash_path,
            fn,
            methods=methods,
            include_in_schema=False,
            **kwargs,
        )
        return fn
    return deco


@router.post("/invite_user/{email_address}", response_model=SendRegistrationInviteResponse)
@_slash("/invite_user/{email_address}", ["POST"], response_model=SendRegistrationInviteResponse)
def invite_user(
    email_address: EmailStr = Path(..., description="Email of the person to invite"),
    admin=Depends(require_admin),
):
    """Email a one-time signup code to this address. They must enter it to register."""
    return send_registration_invite(admin_id=admin.id, email=email_address)


@router.get("/verify")
@_slash("/verify", ["GET"])
def verify_admin_access(admin=Depends(require_admin)):
    """
    Administrative check endpoint:
    Verifies that the caller holds the administrator role and that their
    current sign-in has been verified with MFA.
    """
    return {
        "status": "ok",
        "message": "Administrative access verified.",
        "admin_id": admin.id,
    }


@router.get("/account", response_model=AdminAccountResponse)
@_slash("/account", ["GET"], response_model=AdminAccountResponse)
def get_account(admin=Depends(require_admin)):
    """
    Returns the signed-in administrator's account details for the account screen:
    profile picture, full name, username and the date they became an administrator.
    """
    return get_admin_account_details(admin_id=admin.id)


@router.get("/counts", response_model=AdminCountsResponse)
@_slash("/counts", ["GET"], response_model=AdminCountsResponse)
def get_counts(admin=Depends(require_admin)):
    """
    Returns the total number of registered users and the total number of events,
    split into past, upcoming and cancelled. A cancelled event counts only as cancelled.
    """
    return get_admin_counts()


_USER_LIST_FILTERS = ("administrators", "suspended", "with_warnings")


def _user_list_filter(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized or normalized in ("all", "none", "undefined", "null"):
        return None
    if normalized not in _USER_LIST_FILTERS:
        raise HTTPException(status_code=422, detail="Invalid user list filter.")
    return normalized


@router.get("/users", response_model=AdminUserListResponse)
@router.get("/users/", response_model=AdminUserListResponse, include_in_schema=False)
def get_users(
    search: Optional[str] = Query(None, max_length=SEARCH_TEXT_MAX_LENGTH, description="Case-insensitive substring search by username"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    filter: Optional[str] = Query(
        None, max_length=64, description="One user list counter, combined with the search"),
    admin=Depends(require_admin),
):
    """
    Returns every registered account in pages, each with its profile picture,
    full name, username and identifier. An account without a username is returned with its full name.
    Supports case-insensitive search by username across all accounts, together with one counter filter.
    Each user entry has its number of warnings that count and its status; an administrator's entry the role only.
    """
    return list_admin_users(search=search, page=page, limit=limit, filter_by=_user_list_filter(filter))


# Must stay ABOVE /users/{user_id}, or FastAPI reads "counters" as a user id.
@router.get("/users/counters", response_model=AdminUserListCounters)
@_slash("/users/counters", ["GET"], response_model=AdminUserListCounters)
def get_users_counters(admin=Depends(require_admin)):
    """The user list counters: Administrators, Suspended and With warnings."""
    return get_user_list_counters()


@router.get("/users/{user_id}", response_model=AdminUserDetailResponse)
@_slash("/users/{user_id}", ["GET"], response_model=AdminUserDetailResponse)
def get_user(
    user_id: str = Path(..., description="Target user identifier"),
    admin=Depends(require_admin),
):
    """
    Returns a user's details: profile picture, full name, username, creation date,
    whether the account is an administrator, and the events they organize and have joined,
    split into past, upcoming and cancelled.
    """
    return get_admin_user_details(user_id=user_id)


@router.post("/users/{user_id}/grant-admin", response_model=GrantAdminRoleResponse)
@_slash("/users/{user_id}/grant-admin", ["POST"], response_model=GrantAdminRoleResponse)
def grant_admin(
    user_id: str = Path(..., description="Target user identifier"),
    admin=Depends(require_admin),
):
    """
    Grants the administrator role to another account that is not an administrator.
    Refuses if the account already is an administrator.
    Offers no way to remove the administrator role.
    """
    return grant_admin_role(target_user_id=user_id, admin_user_id=admin.id)


_EVENT_LIST_FILTERS = ("all", "past", "upcoming", "cancelled")


def _event_list_filter(*values: Optional[str]) -> str:
    for value in values:
        if value is None:
            continue
        normalized = value.strip().lower()
        if not normalized or normalized in ("none", "undefined", "null"):
            continue
        if normalized not in _EVENT_LIST_FILTERS:
            raise HTTPException(status_code=422, detail="Invalid event list filter.")
        return normalized
    return "all"


@router.get("/events", response_model=AdminEventListResponse)
@router.get("/events/", response_model=AdminEventListResponse, include_in_schema=False)
def get_events(
    status_filter: Optional[str] = Query(None, description="Filter list: all, past, upcoming, cancelled"),
    filter: Optional[str] = Query(None, description="Alias for status_filter"),
    status: Optional[str] = Query(None, description="Alias for status_filter"),
    search: Optional[str] = Query(None, max_length=SEARCH_TEXT_MAX_LENGTH, description="Case-insensitive substring search by event title"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    admin=Depends(require_admin),
):
    """
    Returns events in pages across four lists: all events, past, upcoming and cancelled.
    Each list covers every event in the application. A cancelled event appears only in all
    and cancelled, never in past or upcoming.
    Supports case-insensitive search by title.
    """
    return list_admin_events(
        status_filter=_event_list_filter(status_filter, filter, status),
        search=search,
        page=page,
        limit=limit,
    )


@router.get("/events/{event_id}", response_model=AdminEventDetailResponse)
@_slash("/events/{event_id}", ["GET"], response_model=AdminEventDetailResponse)
def get_event(
    event_id: str = Path(..., description="Target event identifier"),
    admin=Depends(require_admin),
):
    """
    Returns an event's details, for past, upcoming and cancelled events:
    everything the event details page shows, whether it is cancelled,
    and its participant list with profile picture, full name and username.
    """
    return get_admin_event_details(event_id=event_id)

@router.post("/users/{user_id}/warnings", response_model=WarningHistoryItem, status_code=201)
@_slash("/users/{user_id}/warnings", ["POST"], response_model=WarningHistoryItem, status_code=201)
def post_warning(
    body: GiveWarningRequest,
    user_id: str = Path(..., description="User to warn"),
    admin=Depends(require_admin),
):
    """Gives a user account a warning with a written reason. Refused without a reason or for an administrator."""
    return give_warning(user_id=user_id, admin_id=admin.id, reason=body.reason,
                        about_type=body.about_type, about_id=body.about_id)


@router.get("/users/{user_id}/warnings", response_model=WarningHistoryResponse)
@_slash("/users/{user_id}/warnings", ["GET"], response_model=WarningHistoryResponse)
def get_user_warnings(
    user_id: str = Path(..., description="Target user identifier"),
    admin=Depends(require_admin),
):
    """A user's warning history, newest first, including withdrawn warnings."""
    return get_warning_history(user_id=user_id)


@router.post("/warnings/{warning_id}/withdraw", response_model=WarningHistoryItem)
@_slash("/warnings/{warning_id}/withdraw", ["POST"], response_model=WarningHistoryItem)
def post_withdraw_warning(
    warning_id: int = Path(..., description="Warning to withdraw"),
    admin=Depends(require_admin),
):
    """Withdraws a warning given by mistake. It stays in the history and no longer counts."""
    return withdraw_warning(warning_id=warning_id, admin_id=admin.id)


@router.get("/audit-log", response_model=AuditLogResponse)
@_slash("/audit-log", ["GET"], response_model=AuditLogResponse)
def get_audit_log(
    before: Optional[str] = Query(None, description="next_before of the previous page"),
    limit: int = Query(20, ge=1, le=100),
    admin=Depends(require_admin),
):
    """Every administrative action, newest first, page by page."""
    return list_audit_log(before=before, limit=limit)

@router.post("/users/{user_id}/suspend", response_model=SuspensionResponse)
@_slash("/users/{user_id}/suspend", ["POST"], response_model=SuspensionResponse)
def post_suspend(
    body: SuspensionReasonRequest,
    user_id: str = Path(..., description="User account to suspend"),
    admin=Depends(require_admin),
):
    """
    Suspends a user account with a written reason, until an administrator lifts it.
    The account can no longer sign in or use the application, its upcoming events are
    cancelled and it leaves the upcoming events it joined. Refused for an administrator.
    """
    return suspend_user(user_id=user_id, admin_id=admin.id, reason=body.reason)


@router.post("/users/{user_id}/lift-suspension", response_model=SuspensionResponse)
@_slash("/users/{user_id}/lift-suspension", ["POST"], response_model=SuspensionResponse)
def post_lift_suspension(
    body: SuspensionReasonRequest,
    user_id: str = Path(..., description="Suspended user account"),
    admin=Depends(require_admin),
):
    """Lifts a suspension with a written reason and emails the user. Cancelled events stay cancelled."""
    return lift_suspension(user_id=user_id, admin_id=admin.id, reason=body.reason)