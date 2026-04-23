"""
Run this directly to debug the reminder job:
    python debug_reminder.py

It bypasses the scheduler and prints every step so you can see exactly
where things are failing.
"""
import logging
import sys
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

# Show all logs in the console
logging.basicConfig(
    level=logging.DEBUG,
    format="%(levelname)s | %(name)s | %(message)s",
    stream=sys.stdout,
)

from app.db.supabase_client import supabase
from app.core.config import settings

print("\n=== CONFIG CHECK ===")
print(f"SMTP_HOST     : {settings.SMTP_HOST}")
print(f"SMTP_PORT     : {settings.SMTP_PORT}")
print(f"SMTP_USER     : {settings.SMTP_USER}")
print(f"SMTP_PASSWORD : {'SET' if settings.SMTP_PASSWORD else 'NOT SET'}")
print(f"EMAIL_FROM    : {settings.EMAIL_FROM}")
print(f"SUPABASE_URL  : {settings.SUPABASE_URL}")

print("\n=== TIME WINDOW ===")
now = datetime.now(timezone.utc)
window_start = now + timedelta(minutes=2)
window_end = window_start + timedelta(minutes=1)
print(f"Now          : {now.isoformat()}")
print(f"Window start : {window_start.isoformat()}")
print(f"Window end   : {window_end.isoformat()}")

print("\n=== QUERYING EVENTS ===")
response = (
    supabase.table("events")
    .select("*")
    .eq("status", "active")
    .gte("start_datetime", window_start.isoformat())
    .lte("start_datetime", window_end.isoformat())
    .execute()
)
events = response.data or []
print(f"Events found : {len(events)}")
for e in events:
    print(f"  - [{e['id']}] {e['title']} | start: {e['start_datetime']} | status: {e['status']}")

if not events:
    print("\n>>> No events in window. Try creating an event with start_datetime between:")
    print(f"    {window_start.isoformat()}")
    print(f"    {window_end.isoformat()}")
    sys.exit(0)

for event in events:
    event_id = event["id"]
    title = event["title"]
    print(f"\n=== EVENT: {title} ({event_id}) ===")

    participants = supabase.table("event_participants").select("user_id").eq("event_id", event_id).execute()
    saved = supabase.table("saved_events").select("user_id").eq("event_id", event_id).execute()

    participant_ids = [r["user_id"] for r in (participants.data or [])]
    saved_ids = [r["user_id"] for r in (saved.data or [])]
    all_user_ids = list(set(participant_ids + saved_ids))

    print(f"Participants : {participant_ids}")
    print(f"Saved by     : {saved_ids}")
    print(f"Total users  : {len(all_user_ids)}")

    if not all_user_ids:
        print(">>> No users attending or saved this event — no emails to send.")
        continue

    for user_id in all_user_ids:
        print(f"\n  User: {user_id}")

        # Check already reminded
        notif = supabase.table("notifications").select("id").eq("user_id", user_id).eq("event_id", event_id).eq("type", "reminder").execute()
        if notif.data:
            print(f"  >>> Already reminded, skipping.")
            continue

        # Fetch email
        try:
            auth_response = supabase.auth.admin.get_user_by_id(user_id)
            email = auth_response.user.email if auth_response and auth_response.user else None
        except Exception as ex:
            print(f"  >>> Failed to fetch email: {ex}")
            email = None

        print(f"  Email: {email}")

        if not email:
            print(f"  >>> No email found, skipping.")
            continue

        # Try sending
        from app.services.email_service import send_email, build_reminder_email
        subject, plain, html = build_reminder_email(event)
        print(f"  Sending: {subject}")
        send_email(email, subject, plain, html)
        print(f"  >>> Done (check logs above for errors)")
