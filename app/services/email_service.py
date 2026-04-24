import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.core.config import settings

logger = logging.getLogger(__name__)


def send_email(to_email: str, subject: str, body: str, html_body: str = None):
    """Send an email via SMTP. Logs and swallows failures so callers are unaffected."""
    try:
        if html_body:
            msg = MIMEMultipart("alternative")
            msg.attach(MIMEText(body, "plain"))
            msg.attach(MIMEText(html_body, "html"))
        else:
            msg = MIMEText(body, "plain")

        msg["Subject"] = subject
        msg["From"] = settings.EMAIL_FROM
        msg["To"] = to_email

        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)

        logger.info(f"Email sent to {to_email}: {subject}")

    except Exception as e:
        logger.error(f"Email failed to {to_email}: {e}")


def _fmt_dt(dt_str: str) -> str:
    try:
        from datetime import datetime as dt_cls
        dt = dt_cls.fromisoformat(dt_str.replace("Z", "+00:00"))
        return dt.strftime("%A, %B %d, %Y at %I:%M %p UTC")
    except Exception:
        return dt_str


def _event_detail_rows(event: dict) -> tuple[str, str]:
    """Shared helper — returns (plain_lines, html_rows) for event detail fields."""
    title        = event.get("title") or "Event"
    description  = event.get("description") or "No description provided."
    location     = event.get("location_name") or "Location TBD"
    start_dt     = event.get("start_datetime", "")
    category     = event.get("category") or "General"
    cost         = event.get("cost", 0)
    capacity     = event.get("max_capacity")
    cost_str     = "Free" if not cost or cost == 0 else f"${cost}"
    capacity_str = str(capacity) if capacity else "Unlimited"

    start_fmt = _fmt_dt(start_dt)

    plain_lines = (
        f"  Title    : {title}\n"
        f"  Starts   : {start_fmt}\n"
        f"  Location : {location}\n"
        f"  Category : {category}\n"
        f"  Cost     : {cost_str}\n"
        f"  Capacity : {capacity_str}\n\n"
        f"About this event:\n{description}"
    )

    html_rows = f"""
        <h3 style="margin: 0 0 16px; color: #1F2937; font-size: 20px;">{title}</h3>
        <table style="width: 100%; border-collapse: collapse;">
          <tr><td style="padding:6px 0;color:#6B7280;width:110px;">&#128197; Starts</td><td style="padding:6px 0;font-weight:600;">{start_fmt}</td></tr>
          <tr><td style="padding:6px 0;color:#6B7280;">&#128205; Location</td><td style="padding:6px 0;font-weight:600;">{location}</td></tr>
          <tr><td style="padding:6px 0;color:#6B7280;">&#127991; Category</td><td style="padding:6px 0;font-weight:600;">{category}</td></tr>
          <tr><td style="padding:6px 0;color:#6B7280;">&#128176; Cost</td><td style="padding:6px 0;font-weight:600;">{cost_str}</td></tr>
          <tr><td style="padding:6px 0;color:#6B7280;">&#128101; Capacity</td><td style="padding:6px 0;font-weight:600;">{capacity_str}</td></tr>
        </table>
        <p style="margin-top:12px;"><strong>About this event:</strong></p>
        <p style="color:#4B5563;">{description}</p>
    """

    return plain_lines, html_rows


def build_reminder_email(event: dict) -> tuple[str, str, str]:
    """Return (subject, plain_text, html) for a 2-hour event reminder."""
    title        = event.get("title") or "Upcoming Event"
    start_fmt    = _fmt_dt(event.get("start_datetime", ""))
    plain_lines, html_rows = _event_detail_rows(event)

    subject = f"Reminder: \"{title}\" starts in 2 hours"

    plain = (
        f"Hi there,\n\n"
        f"Your event is starting in 2 hours — here are the details:\n\n"
        f"{plain_lines}\n\n"
        f"See you there!\n"
        f"— The E-VENT Team"
    )

    html = f"""
    <html>
      <body style="font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: auto; padding: 20px;">
        <h2 style="color: #4F46E5;">&#9200; Your event starts in 2 hours!</h2>
        <p>Hi there,</p>
        <p>Here's everything you need to know before you head out:</p>
        <div style="background: #F3F4F6; border-radius: 8px; padding: 20px; margin: 20px 0;">
          {html_rows}
        </div>
        <p style="margin-top: 24px;">See you there!<br><strong>&#8212; The E-VENT Team</strong></p>
        <hr style="border: none; border-top: 1px solid #E5E7EB; margin-top: 32px;" />
        <p style="font-size: 12px; color: #9CA3AF;">
          You received this email because you are attending or have saved this event.
        </p>
      </body>
    </html>
    """

    return subject, plain, html


def build_update_email(event: dict) -> tuple[str, str, str]:
    """Return (subject, plain, html) for an event-updated notification."""
    title = event.get("title") or "Event"
    subject = f"Update: \"{title}\" has been updated"
    plain_lines, html_rows = _event_detail_rows(event)

    plain = (
        f"Hi there,\n\n"
        f"An event you're attending has been updated. Here are the latest details:\n\n"
        f"{plain_lines}\n\n"
        f"— The E-VENT Team"
    )

    html = f"""
    <html>
      <body style="font-family:Arial,sans-serif;color:#333;max-width:600px;margin:auto;padding:20px;">
        <h2 style="color:#F59E0B;">&#9998; Event Updated</h2>
        <p>Hi there,</p>
        <p>An event you're attending has been updated. Here are the latest details:</p>
        <div style="background:#F3F4F6;border-radius:8px;padding:20px;margin:20px 0;">
          {html_rows}
        </div>
        <p style="margin-top:24px;">— <strong>The E-VENT Team</strong></p>
        <hr style="border:none;border-top:1px solid #E5E7EB;margin-top:32px;" />
        <p style="font-size:12px;color:#9CA3AF;">You received this because you are attending this event.</p>
      </body>
    </html>
    """

    return subject, plain, html


def build_cancellation_email(event: dict) -> tuple[str, str, str]:
    """Return (subject, plain, html) for an event-cancelled notification."""
    title = event.get("title") or "Event"
    subject = f"Cancelled: \"{title}\" has been cancelled"
    plain_lines, html_rows = _event_detail_rows(event)

    plain = (
        f"Hi there,\n\n"
        f"We're sorry to let you know that the following event has been cancelled:\n\n"
        f"{plain_lines}\n\n"
        f"We hope to see you at a future event.\n"
        f"— The E-VENT Team"
    )

    html = f"""
    <html>
      <body style="font-family:Arial,sans-serif;color:#333;max-width:600px;margin:auto;padding:20px;">
        <h2 style="color:#EF4444;">&#10060; Event Cancelled</h2>
        <p>Hi there,</p>
        <p>We're sorry to let you know that the following event has been <strong>cancelled</strong>:</p>
        <div style="background:#FEF2F2;border-radius:8px;padding:20px;margin:20px 0;border-left:4px solid #EF4444;">
          {html_rows}
        </div>
        <p>We hope to see you at a future event.</p>
        <p style="margin-top:24px;">— <strong>The E-VENT Team</strong></p>
        <hr style="border:none;border-top:1px solid #E5E7EB;margin-top:32px;" />
        <p style="font-size:12px;color:#9CA3AF;">You received this because you were attending this event.</p>
      </body>
    </html>
    """

    return subject, plain, html


def build_join_confirmation_email(event: dict) -> tuple[str, str, str]:
    """Email to the participant confirming they joined an event."""
    title = event.get("title") or "Event"
    subject = f"You're going to \"{title}\"!"
    plain_lines, html_rows = _event_detail_rows(event)

    plain = (
        f"Hi there,\n\n"
        f"You've successfully joined the following event:\n\n"
        f"{plain_lines}\n\n"
        f"See you there!\n"
        f"— The E-VENT Team"
    )

    html = f"""
    <html>
      <body style="font-family:Arial,sans-serif;color:#333;max-width:600px;margin:auto;padding:20px;">
        <h2 style="color:#10B981;">&#10003; You're going!</h2>
        <p>Hi there,</p>
        <p>You've successfully joined the following event:</p>
        <div style="background:#F0FDF4;border-radius:8px;padding:20px;margin:20px 0;border-left:4px solid #10B981;">
          {html_rows}
        </div>
        <p style="margin-top:24px;">See you there!<br><strong>&#8212; The E-VENT Team</strong></p>
        <hr style="border:none;border-top:1px solid #E5E7EB;margin-top:32px;" />
        <p style="font-size:12px;color:#9CA3AF;">You received this because you joined this event.</p>
      </body>
    </html>
    """

    return subject, plain, html


def build_removed_from_event_email(event: dict) -> tuple[str, str, str]:
    """Email to a participant who was removed from an event by the organizer."""
    title = event.get("title") or "Event"
    subject = f"You've been removed from \"{title}\""
    plain_lines, html_rows = _event_detail_rows(event)

    plain = (
        f"Hi there,\n\n"
        f"You have been removed from the following event by the organizer:\n\n"
        f"{plain_lines}\n\n"
        f"If you think this was a mistake, please contact the event organizer.\n"
        f"— The E-VENT Team"
    )

    html = f"""
    <html>
      <body style="font-family:Arial,sans-serif;color:#333;max-width:600px;margin:auto;padding:20px;">
        <h2 style="color:#EF4444;">&#9888; Removed from Event</h2>
        <p>Hi there,</p>
        <p>You have been <strong>removed</strong> from the following event by the organizer:</p>
        <div style="background:#FEF2F2;border-radius:8px;padding:20px;margin:20px 0;border-left:4px solid #EF4444;">
          {html_rows}
        </div>
        <p>If you think this was a mistake, please contact the event organizer.</p>
        <p style="margin-top:24px;">— <strong>The E-VENT Team</strong></p>
        <hr style="border:none;border-top:1px solid #E5E7EB;margin-top:32px;" />
        <p style="font-size:12px;color:#9CA3AF;">You received this because you were a participant of this event.</p>
      </body>
    </html>
    """

    return subject, plain, html
