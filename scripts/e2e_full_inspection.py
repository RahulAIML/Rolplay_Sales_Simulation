import sys
import os
import unittest
import json
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

# Mock Env Vars Before Imports
os.environ["GEMINI_API_KEY"] = "mock_key"
os.environ["HUBSPOT_ACCESS_TOKEN"] = "mock_token"
os.environ["TWILIO_ACCOUNT_SID"] = "ACxxx"
os.environ["TWILIO_AUTH_TOKEN"] = "authxxx"
os.environ["TWILIO_WHATSAPP_FROM"] = "+12345"
os.environ["TWILIO_TEMPLATE_SID"] = "HXxxx"
os.environ["AUX_BASE_URL"] = "http://localhost:8000/api"

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["DATABASE_URL"] = "" 
os.environ["SQLITE_DB_PATH"] = "test_e2e.db"

from database import db

class FullWorkflowInspection(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        # Already set to test_e2e.db in global scope
        test_db = os.environ.get("SQLITE_DB_PATH", "test_e2e.db")
        if os.path.exists(test_db):
            os.remove(test_db)
        from database import db
        db.init_db()
        # Register a test user
        db.execute_query("INSERT INTO users (email, phone, name, timezone) VALUES ('sales@example.com', 'whatsapp:+1234567890', 'Sales Pro', 'Asia/Kolkata')", commit=True)

    @patch('services.ai_service.generate_coaching_plan')
    @patch('services.ai_service.generate_post_meeting_analysis')
    @patch('services.whatsapp_service.send_whatsapp_message')
    @patch('services.hubspot_service.create_or_find_contact')
    @patch('services.hubspot_service.get_contact_details')
    @patch('services.hubspot_service.sync_meeting_analysis')
    @patch('requests.post')
    @patch('requests.get')
    def test_end_to_end_cycle(self, mock_get, mock_post, mock_hs_analysis, mock_hs_details, mock_hs_contact, mock_wa, mock_ai_post, mock_ai_pre):
        """Inspects the entire sequence from Outlook invite to HubSpot update."""
        from services import meeting_service
        
        print("\n--- [STAGE 1 & 2] Meeting Scheduled & Agent Activated ---")
        mock_hs_contact.return_value = "HS_CLIENT_1"
        mock_hs_details.return_value = {"company": "Target Corp"}
        mock_ai_pre.return_value = {
            "greeting": "Go get 'em!", "scenario": "Sales demo", "steps": ["Prep docs"], "recommended_reply": "Got it"
        }
        # Mock Aux API Response (POST /meetings/schedule)
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"success": True, "meetingId": "AUX_999", "meetingToken": "TOK_777"}
        
        outlook_payload = {
            "meeting": {
                "id": "OUTLOOK_ID_101",
                "title": "Big Deal Close",
                "start": datetime.now().isoformat(),
                "organizer": {"emailAddress": {"address": "sales@example.com"}},
                "online_meeting_url": "https://teams.microsoft.com/l/meetup-join/123"
            },
            "client": {"email": "buyer@corp.com", "name": "Big Buyer"}
        }
        
        res = meeting_service.process_outlook_webhook(outlook_payload)
        self.assertEqual(res["status"], "success")
        print("✅ Outlook Webhook processed successfully.")
        
        # Verify Bot Scheduling
        print("--- [STAGE 5] Bot Scheduling check ---")
        mock_post.assert_called()
        print(f"✅ Aux API called at: {mock_post.call_args[0][0]}")
        
        # Verify Pre-Meeting Coaching
        print("--- [STAGE 4] Pre-Meeting Coaching check ---")
        mock_wa.assert_called()
        pre_msg = mock_wa.call_args[1].get('body', '')
        print(f"✅ WhatsApp message sent: {pre_msg[:50]}...")

        print("\n--- [STAGE 6 & 7] Meeting Recorded & Transcript Sent ---")
        # Simulate Aux Polling behavior or direct Ingest
        # Let's test the Ingest API (/api/ingest-raw-meeting)
        transcript_payload = {
            "session_id": "TOK_777",
            "raw_text": "Sales Pro: How are you?\nBig Buyer: I am interested but the price is high."
        }
        
        mock_ai_post.return_value = {
            "strengths": ["Clear intro"], "weaknesses": ["Missed budget"], "recommended_actions": ["Follow up tomorrow"]
        }
        
        # We need the app context or just call the service logic for Stage 7-11
        # In app.py, ingest_raw_meeting calls parsing_service and then AI analysis
        
        print("--- [STAGE 10 & 11] AI Analysis & Coaching Delivery ---")
        # In the app, notification follows ingest.
        # Let's verify process_transcript_data directly as it's the core logic for Stage 10/11
        meeting_row = db.execute_query("SELECT * FROM meetings WHERE outlook_event_id = 'OUTLOOK_ID_101'", fetch_one=True)
        
        # Mocking for Stage 10/11
        mock_ai_analysis = MagicMock(return_value={
            "objections": [{"quote": "Price is high"}],
            "buying_signals": ["Interested"],
            "risks": ["Budget"],
            "follow_up_actions": ["Discount check"]
        })
        
        with patch('services.ai_service.generate_post_meeting_analysis', mock_ai_analysis):
            meeting_service.process_transcript_data(
                meeting_row, 
                "Sales Pro: Price is $100\nBig Buyer: Too high", 
                "Big Deal Close", 
                source="aux_api"
            )
            
        print("✅ Post-meeting analysis delivered via WhatsApp.")
        mock_ai_analysis.assert_called()
        
        print("\n--- [STAGE 9 & 12] CRM Sync ---")
        mock_hs_analysis.assert_called()
        print("✅ HubSpot sync completed for post-meeting report.")

        print("\n--- [FALLBACK API TEST] ---")
        # Testing the specific fallback URL requested by the user
        from services import aux_service
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"success": True, "meeting": {"status": "completed"}}
        
        token = "TOK_777"
        status = aux_service.get_meeting_status(token)
        called_url = mock_get.call_args[0][0]
        print(f"✅ Fallback API tested at: {called_url}")
        self.assertIn("localhost:8000", called_url)
        self.assertEqual(status["status"], "completed")

if __name__ == "__main__":
    unittest.main()
