import logging
from fastapi import APIRouter, Depends
from app.core.dependencies import require_admin

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
