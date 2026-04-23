"""
Tests update and cancellation emails end-to-end.
Run with: python test_event_emails.py

Steps:
  1. Creates a test event
  2. Joins you as a participant
  3. Triggers an update  → you should receive an update email
  4. Cancels the event   → you should receive a cancellation email
"""
import time
from dotenv import load_dotenv
load_dotenv()

from app.db.supabase_client import supabase
from app.services.event_service import update_event, cancel_event
from datetime import datetime, timezone, timedelta

USER_ID = "8b8db79c-c44d-48a6-888c-0dc0aac6fb4e"

# ── 1. Create event ──────────────────────────────────────────────────────────
print("Creating test event...")
start_dt = datetime.now(timezone.utc) + timedelta(hours=5)
ev = supabase.table("events").insert({
    "title": "Email Test Event",
    "description": "Testing update and cancellation emails.",
    "status": "active",
    "category": "Technology",
    "location_name": "Online / Zoom",
    "cost": 0,
    "max_capacity": 100,
    "start_datetime": start_dt.isoformat(),
    "end_datetime": (start_dt + timedelta(hours=2)).isoformat(),
    "created_by": USER_ID,
}).execute()

event = ev.data[0]
event_id = event["id"]
print(f"  Created: {event_id} — {event['title']}")

# ── 2. Join as participant ───────────────────────────────────────────────────
supabase.table("event_participants").insert({
    "user_id": USER_ID,
    "event_id": event_id,
    "status": "going",
}).execute()
print(f"  Joined as participant")

# ── 3. Trigger update email ──────────────────────────────────────────────────
print("\nUpdating event — you should receive an UPDATE email...")
update_event(USER_ID, event_id, {
    "title": "Email Test Event (Updated)",
    "description": "The event details have changed. New venue confirmed!",
    "location_name": "Conference Room A, Tech Hub",
})
print("  Update done.")

time.sleep(2)

# ── 4. Trigger cancellation email ────────────────────────────────────────────
print("\nCancelling event — you should receive a CANCELLATION email...")
cancel_event(USER_ID, event_id)
print("  Cancellation done.")

print("\nDone. Check your inbox for 2 emails.")
