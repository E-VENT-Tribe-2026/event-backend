import logging
from typing import Literal, Optional
from fastapi import APIRouter, Depends, Query, Path
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


logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/verify")
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
def get_account(admin=Depends(require_admin)):
    """
    Returns the signed-in administrator's account details for the account screen:
    profile picture, full name, username and the date they became an administrator.
    """
    return get_admin_account_details(admin_id=admin.id)


@router.get("/counts", response_model=AdminCountsResponse)
def get_counts(admin=Depends(require_admin)):
    """
    Returns the total number of registered users and the total number of events,
    split into past, upcoming and cancelled. A cancelled event counts only as cancelled.
    """
    return get_admin_counts()


@router.get("/users", response_model=AdminUserListResponse)
def get_users(
    search: Optional[str] = Query(None,max_length=SEARCH_TEXT_MAX_LENGTH, description="Case-insensitive substring search by username"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    filter: Optional[Literal["administrators", "suspended", "with_warnings"]] = Query(
        None, description="One user list counter, combined with the search"),
    admin=Depends(require_admin),
):
    """
    Returns every registered account in pages, each with its profile picture,
    full name, username and identifier. An account without a username is returned with its full name.
    Supports case-insensitive search by username across all accounts, together with one counter filter.
    Each user entry has its number of warnings that count and its status; an administrator's entry the role only.
    """
    return list_admin_users(search=search, page=page, limit=limit, filter_by=filter)


# Must stay ABOVE /users/{user_id}, or FastAPI reads "counters" as a user id.
@router.get("/users/counters", response_model=AdminUserListCounters)
def get_users_counters(admin=Depends(require_admin)):
    """The user list counters: Administrators, Suspended and With warnings."""
    return get_user_list_counters()


@router.get("/users/{user_id}", response_model=AdminUserDetailResponse)
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


@router.get("/events", response_model=AdminEventListResponse)
def get_events(
    status_filter: str = Query("all", description="Filter list: all, past, upcoming, cancelled"),
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
    return list_admin_events(status_filter=status_filter, search=search, page=page, limit=limit)


@router.get("/events/{event_id}", response_model=AdminEventDetailResponse)
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
def post_warning(
    body: GiveWarningRequest,
    user_id: str = Path(..., description="User to warn"),
    admin=Depends(require_admin),
):
    """Gives a user account a warning with a written reason. Refused without a reason or for an administrator."""
    return give_warning(user_id=user_id, admin_id=admin.id, reason=body.reason,
                        about_type=body.about_type, about_id=body.about_id)


@router.get("/users/{user_id}/warnings", response_model=WarningHistoryResponse)
def get_user_warnings(
    user_id: str = Path(..., description="Target user identifier"),
    admin=Depends(require_admin),
):
    """A user's warning history, newest first, including withdrawn warnings."""
    return get_warning_history(user_id=user_id)


@router.post("/warnings/{warning_id}/withdraw", response_model=WarningHistoryItem)
def post_withdraw_warning(
    warning_id: int = Path(..., description="Warning to withdraw"),
    admin=Depends(require_admin),
):
    """Withdraws a warning given by mistake. It stays in the history and no longer counts."""
    return withdraw_warning(warning_id=warning_id, admin_id=admin.id)


@router.get("/audit-log", response_model=AuditLogResponse)
def get_audit_log(
    before: Optional[str] = Query(None, description="next_before of the previous page"),
    limit: int = Query(20, ge=1, le=100),
    admin=Depends(require_admin),
):
    """Every administrative action, newest first, page by page."""
    return list_audit_log(before=before, limit=limit)