from fastapi import APIRouter, Header, HTTPException
from app.core.config import settings
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/trigger")
def trigger_reminders(x_cron_secret: str = Header(default=None)):
    """
    Called by the Render Cron Job every hour to send event reminder emails.
    Protected by a shared secret header to prevent public abuse.
    """
    if settings.CRON_SECRET and x_cron_secret != settings.CRON_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    from app.services.reminder_service import send_event_reminders
    from app.services.invitation_service import run_invitation_purge

    # #207: the hourly Render cron also clears invitations to started events, in case
    # the in-process scheduler was asleep (free Render instances spin down).
    run_invitation_purge()
    try:
        send_event_reminders()
        return {"status": "ok", "message": "Reminder job completed"}
    except Exception as e:
        logger.error(f"Reminder job failed: {e}")
        raise HTTPException(status_code=500, detail="Reminder job failed. Check server logs.")
