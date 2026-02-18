
import os
import sys
import unittest
import json
from unittest.mock import MagicMock, patch

# Mock Env Vars Before Imports
os.environ["GEMINI_API_KEY"] = "mock_key"
os.environ["HUBSPOT_ACCESS_TOKEN"] = "mock_token"
os.environ["TWILIO_ACCOUNT_SID"] = "ACxxx"
os.environ["TWILIO_AUTH_TOKEN"] = "authxxx"
os.environ["TWILIO_WHATSAPP_FROM"] = "+12345"
os.environ["TWILIO_TEMPLATE_SID"] = "HXxxx"

from datetime import datetime, timedelta

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import meeting_service, whatsapp_service, ai_service, hubspot_service, aux_service
from database import db

class TestCoordinationCycle(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        # Use in-memory DB for tests
        os.environ["DATABASE_URL"] = ":memory:"
        db.init_db()
        # Ensure test user exists
        db.execute_query("INSERT INTO users (email, phone, name, timezone) VALUES ('test@example.com', '+1234567890', 'Test Sp', 'Asia/Kolkata')", commit=True)

    @patch('services.ai_service.generate_coaching_plan')
    @patch('services.whatsapp_service.send_whatsapp_message')
    @patch('services.hubspot_service.create_or_find_contact')
    @patch('services.hubspot_service.get_contact_details')
    @patch('services.aux_service.schedule_meeting')
    def test_pre_meeting_flow(self, mock_aux, mock_hs_details, mock_hs_contact, mock_wa, mock_ai):
        """Tests the Activate Agent -> Activate Coach -> Pre-Meeting Training loop."""
        
        # Mocks
        mock_hs_contact.return_value = "HS123"
        mock_hs_details.return_value = {"jobtitle": "CEO", "company": "Giant Corp"}
        mock_ai.return_value = {
            "greeting": "Hello Test",
            "scenario": "CEO meeting",
            "steps": ["Step 1", "Step 2"],
            "recommended_reply": "Let's talk"
        }
        mock_aux.return_value = {"meetingId": "AUX999", "token": "TOK888"}
        
        # Simulated Webhook Payload
        payload = {
            "meeting": {
                "meeting_id": "OUTLOOK_MTG_1",
                "title": "Strategy Session",
                "start_time": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
                "organizer": {"email": "test@example.com"},
                "online_meeting_url": "https://zoom.us/j/123"
            },
            "client": {
                "email": "client@corp.com",
                "name": "Jane Doe"
            }
        }
        
        # RUN
        from services import meeting_service
        res = meeting_service.process_outlook_webhook(payload)
        
        # VERIFICATIONS
        self.assertEqual(res["status"], "success")
        
        # 1. HubSpot was called before coaching
        mock_hs_contact.assert_called()
        mock_hs_details.assert_called_with("HS123")
        
        # 2. AI Coaching Plan was generated
        mock_ai.assert_called()
        
        # 3. WhatsApp Message was sent with prefix (mock_wa will receive prefixed number)
        mock_wa.assert_called()
        last_call_args = mock_wa.call_args[0]
        self.assertEqual(last_call_args[0], "+1234567890") # number passed to service
        
        # 4. Aux API was scheduled
        mock_aux.assert_called()
        
        # Check DB
        mtg = db.execute_query("SELECT * FROM meetings WHERE outlook_event_id = 'OUTLOOK_MTG_1'", fetch_one=True)
        self.assertIsNotNone(mtg)
        self.assertEqual(mtg['aux_meeting_id'], "AUX999")

    @patch('services.ai_service.generate_post_meeting_analysis')
    @patch('services.whatsapp_service.send_whatsapp_message')
    @patch('services.hubspot_service.sync_meeting_analysis')
    def test_post_meeting_flow(self, mock_hs_sync, mock_wa, mock_ai_analysis):
        """Tests the Send Transcript -> Analyze -> Share -> Update CRM loop."""
        
        # Mock Meeting in DB
        db.execute_query("INSERT OR REPLACE INTO clients (id, email, name) VALUES (99, 'jane@corp.com', 'Jane')", commit=True)
        db.execute_query("INSERT OR REPLACE INTO meetings (id, outlook_event_id, client_id, salesperson_phone, status) VALUES (55, 'OUTLOOK_MTG_1', 99, '+1234567890', 'scheduled')", commit=True)
        
        # Mocks
        mock_ai_analysis.return_value = {
            "objections": [{"quote": "Too expensive"}],
            "buying_signals": ["Interested"],
            "risks": ["Competition"],
            "follow_up_actions": ["Send proposal"]
        }
        
        # Simulated Aux Data
        aux_data = {
            "meetingId": "AUX999",
            "title": "Strategy Session",
            "transcript": {"content": "Speaker 1: Hello\nSpeaker 2: Hi"}
        }
        
        meeting_row = db.execute_query("SELECT * FROM meetings WHERE id=55", fetch_one=True)
        
        # RUN
        from services import meeting_service
        success = meeting_service.process_aux_transcript(meeting_row, aux_data)
        
        # VERIFICATIONS
        self.assertTrue(success)
        
        # 1. AI analyzed transcript
        mock_ai_analysis.assert_called()
        
        # 2. WhatsApp notified SP
        mock_wa.assert_called()
        
        # 3. HubSpot updated
        mock_hs_sync.assert_called()

if __name__ == "__main__":
    unittest.main()
