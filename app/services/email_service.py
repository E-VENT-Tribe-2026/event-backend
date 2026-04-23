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


def build_reminder_email(event: dict) -> tuple[str, str, str]:
    """Return (subject, plain_text, html) for a 12-hour event reminder."""
    title = event.get("title", "Upcoming Event")
    description = event.get("description") or "No description provided."
    location = event.get("location_name") or "Location TBD"
    start_dt = event.get("start_datetime", "")
    category = event.get("category") or "General"
    cost = event.get("cost", 0)
    cost_str = "Free" if not cost or cost == 0 else f"${cost}"

    try:
        from datetime import datetime
        dt = datetime.fromisoformat(start_dt.replace("Z", "+00:00"))
        start_formatted = dt.strftime("%A, %B %d, %Y at %I:%M %p UTC")
    except Exception:
        start_formatted = start_dt

    subject = f"Reminder: \"{title}\" starts in 2 minutes"

    plain = (
        f"Hi there,\n\n"
        f"This is a reminder that an event you're interested in is starting soon!\n\n"
        f"Event: {title}\n"
        f"When: {start_formatted}\n"
        f"Where: {location}\n"
        f"Category: {category}\n"
        f"Cost: {cost_str}\n\n"
        f"Description:\n{description}\n\n"
        f"See you there!\n"
        f"— The E-VENT Team"
    )

    html = f"""
    <html>
      <body style="font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: auto; padding: 20px;">
        <h2 style="color: #4F46E5;">&#9200; Event Reminder</h2>
        <p>Hi there,</p>
        <p>This is a friendly reminder that an event you're interested in is starting in <strong>2 minutes</strong>!</p>
        <div style="background: #F3F4F6; border-radius: 8px; padding: 16px; margin: 20px 0;">
          <h3 style="margin: 0 0 12px; color: #1F2937;">{title}</h3>
          <p style="margin: 4px 0;">&#128197; <strong>When:</strong> {start_formatted}</p>
          <p style="margin: 4px 0;">&#128205; <strong>Where:</strong> {location}</p>
          <p style="margin: 4px 0;">&#127991; <strong>Category:</strong> {category}</p>
          <p style="margin: 4px 0;">&#128176; <strong>Cost:</strong> {cost_str}</p>
        </div>
        <p><strong>About this event:</strong><br>{description}</p>
        <p style="margin-top: 24px;">See you there!<br><strong>&#8212; The E-VENT Team</strong></p>
        <hr style="border: none; border-top: 1px solid #E5E7EB; margin-top: 32px;" />
        <p style="font-size: 12px; color: #9CA3AF;">
          You received this email because you are attending or have saved this event.
        </p>
      </body>
    </html>
    """

    return subject, plain, html
