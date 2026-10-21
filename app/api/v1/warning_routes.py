from fastapi import APIRouter, Depends, Path

from app.core.dependencies import require_regular_user
from app.schemas.warning_schema import PendingWarningsResponse, AcknowledgeWarningResponse
from app.services.warning_service import get_pending_warnings, acknowledge_warning

router = APIRouter()


@router.get("/pending", response_model=PendingWarningsResponse)
def pending_warnings(user=Depends(require_regular_user)):
    """The signed-in user's warnings that wait to be acknowledged, oldest first."""
    return get_pending_warnings(user_id=user.id)


@router.post("/{warning_id}/acknowledge", response_model=AcknowledgeWarningResponse)
def acknowledge(
    warning_id: int = Path(..., description="One of the signed-in user's warnings"),
    user=Depends(require_regular_user),
):
    """Records that the user acknowledged their warning, so no device shows it again."""
    return acknowledge_warning(warning_id=warning_id, user_id=user.id)