"""
Creates a test event starting 2.5 minutes from now, then joins the current user to it.
Run with: python create_test_event.py <your_user_id>
"""
import sys
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

from app.db.supabase_client import supabase

user_id = sys.argv[1] if len(sys.argv) > 1 else None
if not user_id:
    print("Usage: python create_test_event.py <your_user_id>")
    sys.exit(1)

start_dt = datetime.now(timezone.utc) + timedelta(minutes=2, seconds=30)

result = supabase.table("events").insert({
    "title": "Reminder Test Event",
    "description": "Testing the 2-minute reminder email.",
    "status": "active",
    "start_datetime": start_dt.isoformat(),
    "end_datetime": (start_dt + timedelta(hours=1)).isoformat(),
    "created_by": user_id,
}).execute()

event = result.data[0]
event_id = event["id"]
print(f"Created event: {event_id} | starts at {start_dt.isoformat()}")

# Join the event so you're in event_participants
supabase.table("event_participants").insert({
    "user_id": user_id,
    "event_id": event_id,
    "status": "going",
}).execute()
print(f"Joined event as participant.")
print(f"\nNow run: python debug_reminder.py")
print(f"(within the next 30 seconds)")
