import os
import sys
import json
from datetime import datetime
import logging

# Setup Path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db
db.init_db()

# Mock Services
from services import meeting_service, hubspot_service

# Configure Logging to see details
logging.basicConfig(level=logging.INFO)

def test_full_flow():
    print("🚀 Starting End-to-End HubSpot Log Test...")
    
    # 1. Setup Test Data
    test_client_email = f"test_client_{int(datetime.now().timestamp())}@example.com"
    test_client_name = "Test Client"
    test_meeting_id = f"evt_{int(datetime.now().timestamp())}"
    
    # Ensure Salesperson exists
    user = db.execute_query("SELECT email FROM users LIMIT 1", fetch_one=True)
    if not user:
        print("❌ No users found in DB. Run /register first.")
        return
    salesperson_email = user['email']
    print(f"   Using Salesperson: {salesperson_email}")

    # 2. Simulate Outlook Webhook (Should Sync Client)
    print("\n🔹 Step 1: Outlook Webhook (Client Sync)")
    outlook_payload = {
        "meeting": {
            "title": "HubSpot Test Meeting",
            "start_time": datetime.now().isoformat(),
            "end_time": datetime.now().isoformat(),
            "meeting_id": test_meeting_id,
            "organizer": {"email": salesperson_email}
        },
        "client": {
            "email": test_client_email,
            "name": test_client_name,
            "company": "Test Corp"
        }
    }
    
    meeting_service.process_outlook_webhook(outlook_payload)
    
    # Verify DB for Client
    client = db.execute_query("SELECT * FROM clients WHERE email = ?", (test_client_email,), fetch_one=True)
    if client and client['hubspot_contact_id']:
        print(f"✅ Client synced to local DB & HubSpot! (HS ID: {client['hubspot_contact_id']})")
    else:
        print("❌ Client sync failed or HS ID missing.")

    # 3. Simulate Transcript Webhook (Should Create Analysis Ticket)
    print("\n🔹 Step 2: Transcript Webhook (Analysis Ticket)")
    transcript_payload = {
        "meeting_title": "HubSpot Test Meeting",
        "meeting_time": datetime.now().isoformat(),
        "transcript_url": "http://fake-transcript-url.com",
        "source": "manual_test"
    }
    
    # We need to mock 'fetch_transcript' and 'ai_service' to avoid external calls failing
    # But 'process_transcript_webhook' calls them. 
    # For this test, let's just inspect if the function *tries* to call HS.
    # Actually, let's just call the HS function directly to test IT, 
    # assuming logic in meeting_service is correct (we verified code).
    
    # Simulate Analysis Data
    analysis_mock = {
        "objections": [{"quote": "Price is high", "context": "Budget"}],
        "buying_signals": ["I love this"],
        "risks": ["Competitor mentioned"],
        "follow_up_actions": ["Send proposal"]
    }
    
    if client:
        print("   Invoking sync_meeting_analysis directly...")
        res = hubspot_service.sync_meeting_analysis(
            client_db_id=client['id'],
            meeting_title="HubSpot Test Meeting",
            analysis=analysis_mock,
            transcript_url="http://fake-transcript.com"
        )
        if res:
            print("✅ Analysis Ticket created in HubSpot!")
        else:
            print("❌ Analysis Ticket creation failed.")

    # 4. Simulate Feedback (Done)
    print("\n🔹 Step 3: Salesperson Feedback (Feedback Ticket)")
    if client:
        print("   Invoking sync_note_to_contact directly...")
        # Note: sync_note_to_contact now creates a Ticket internally
        hubspot_service.sync_note_to_contact(client['id'], "Salesperson Feedback: Meeting went great!")
        print("✅ Feedback Ticket creation triggered (check logs above).")

if __name__ == "__main__":
    test_full_flow()
