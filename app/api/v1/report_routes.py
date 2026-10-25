from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_onboarded_user
from app.core.user_rate_limit import REPORT_LIMIT, user_rate_limit
from app.schemas.report_schema import ReportConfirmation, ReportCreate
from app.services.report_service import create_report

router = APIRouter()

limit_reports = user_rate_limit("reports", REPORT_LIMIT, user_dep=get_current_onboarded_user)


@router.post(
    "",
    status_code=201,
    response_model=ReportConfirmation,
    summary="Report an event, a user or a chat message",
    description=(
        "Report an event (from its details page or its chat), a user (from their profile) or "
        "another user's message (in an event chat you are in).\n\n"
        "**Errors:**\n"
        "- `400` — own event, own profile or own message; system message.\n"
        "- `403` — the report is opened from an event chat the user is not in.\n"
        "- `404` — event, user or message not found.\n"
        "- `409` — `already_reported`: the user already has an open report about this item.\n"
        "- `422` — reason not allowed for this kind of report, description missing for Other or invalid.\n"
        "- `429` — too many reports in a short time."
    ),
)
def report(body: ReportCreate, user=Depends(limit_reports)):
    return create_report(user.id, body)
