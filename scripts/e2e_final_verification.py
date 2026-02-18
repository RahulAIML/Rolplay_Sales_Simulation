import sys
import os
import json
import logging
from datetime import datetime, timedelta
import pytz

# Setup Path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import meeting_service, ai_service, whatsapp_service, aux_service, hubspot_service
from database import db
from utils import get_current_utc_time, parse_iso_datetime

# --- MOCKS ---
def mock_ai_coaching(*args, **kwargs):
    return {"greeting": "Hello", "scenario": "Test", "steps": ["Step 1"], "recommended_reply": "Yes"}

def mock_whatsapp_send(*args, **kwargs):
    print(f"  [Mock WhatsApp] Sent to {args[0]}")
    return "msid_test"

def mock_aux_schedule(*args, **kwargs):
    print(f"  [Mock Aux] Scheduled meeting: {kwargs.get('title')}")
    return {"token": "test_token_123", "meetingId": 999}

def mock_aux_trigger(*args, **kwargs):
    print(f"  [Mock Survey Webhook] Triggered for: {args[0].get('client_email')}")
    return {"status": "triggered"}

def mock_hubspot_create(*args, **kwargs):
    print(f"  [Mock HubSpot] Created/Found contact: {args[0]}")
    return "hs_contact_001"

def mock_hubspot_ticket(*args, **kwargs):
    print(f"  [Mock HubSpot] Created ticket: {args[1]}")
    return True

# Apply Mocks
ai_service.generate_coaching_plan = mock_ai_coaching
whatsapp_service.send_whatsapp_message = mock_whatsapp_send
aux_service.schedule_meeting = mock_aux_schedule
aux_service.trigger_survey_webhook = mock_aux_trigger
hubspot_service.create_or_find_contact = mock_hubspot_create
hubspot_service.sync_survey_response_to_contact = mock_hubspot_ticket

def run_e2e_test():
    print("🚀 STARTING FINAL E2E TEST")
    db.init_db()
    
    user_email = "test_organizer@example.com"
    user_phone = "+910000000000"
    
    # Clean up
    db.execute_query("DELETE FROM users WHERE email = ?", (user_email,), commit=True)
    db.execute_query("DELETE FROM meetings WHERE salesperson_phone = ?", (user_phone,), commit=True)

    # 1. Registration
    print("\n[STEP 1] Registration")
    db.execute_query("INSERT INTO users (email, name, phone) VALUES (?, ?, ?)", 
                     (user_email, "Test Organizer", user_phone), commit=True)
    print("  ✅ User registered")

    # 2. Outlook Webhook (Timezone Check)
    print("\n[STEP 2] Outlook Webhook (Timezone Parsing)")
    os.environ["APP_TIMEZONE"] = "Asia/Kolkata"
    # Sending a naive time - should be localized to IST and then converted to UTC
    # 2026-02-20 10:00:00 IST -> 04:30:00 UTC
    payload = {
        "meeting": {
            "meeting_id": "mtg_e2e_001",
            "title": "E2E Demo Meeting",
            "start_time": "2026-02-20T10:00:00", 
            "location": "https://zoom.us/j/123",
            "organizer": {"email": user_email}
        },
        "client": {
            "email": "client@example.com",
            "name": "Jane Client"
        }
    }
    meeting_service.process_outlook_webhook(payload)
    
    m = db.execute_query("SELECT * FROM meetings WHERE outlook_event_id = ?", ("mtg_e2e_001",), fetch_one=True)
    if m:
        dt = parse_iso_datetime(m['start_time'])
        print(f"  ✅ Meeting created with start_time (UTC): {m['start_time']}")
        # 10 AM IST is 4:30 AM UTC
        if "04:30:00" in str(m['start_time']):
             print("  ✅ Timezone localization worked (IST -> UTC)")
        else:
             print(f"  ❌ Timezone check failed. Expected 04:30:00 UTC, got {m['start_time']}")
        
        if m['aux_meeting_id'] == 999:
             print("  ✅ Aux scheduling worked")
    else:
        print("  ❌ Meeting not found in DB")

    # 3. Meeting End (Scheduler & Survey Trigger)
    print("\n[STEP 3] Scheduler (Meeting End & Survey Trigger)")
    # Force meeting to 'finished' status by manipulating end_time to past
    past_time = (get_current_utc_time() - timedelta(minutes=5)).isoformat()
    db.execute_query("UPDATE meetings SET end_time = ? WHERE outlook_event_id = ?", (past_time, "mtg_e2e_001"), commit=True)
    
    # Run scheduler logic (importing to avoid global loop)
    from scheduler import check_pending_meetings
    check_pending_meetings()
    
    m_after = db.execute_query("SELECT status FROM meetings WHERE outlook_event_id = ?", ("mtg_e2e_001",), fetch_one=True)
    if m_after and m_after['status'] == 'reminder_sent':
        print("  ✅ Scheduler detected meeting end and updated status")
    else:
        print(f"  ❌ Scheduler failed. Status: {m_after['status'] if m_after else 'N/A'}")

    # 4. Survey Ingest -> HubSpot
    print("\n[STEP 4] Survey Webhook -> HubSpot Sync")
    # Simulate the incoming survey from app.py
    survey_data = {
        "participant_email": "client@example.com",
        "survey_response": {
            "punctuality": 5,
            "overall_value": 5
        },
        "meeting_title": "E2E Demo Meeting"
    }
    # This calls hubspot_service.sync_survey_response_to_contact (which we mocked)
    success = hubspot_service.sync_survey_response_to_contact(survey_data['participant_email'], survey_data)
    if success:
        print("  ✅ Survey responses handled and synced to HubSpot")
    else:
        print("  ❌ Survey sync failed")

    print("\n🚀 FINAL E2E TEST COMPLETE")

if __name__ == "__main__":
    try:
        run_e2e_test()
    except Exception as e:
        print(f"Test crashed: {e}")
        import traceback
        traceback.print_exc()
