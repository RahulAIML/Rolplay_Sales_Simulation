import sys
import os
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

# Mock database and other services before importing meeting_service
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class TestWhatsAppWebhook(unittest.TestCase):
    @patch('services.meeting_service.db')
    @patch('services.meeting_service.whatsapp_service')
    @patch('services.meeting_service.ai_service')
    @patch('services.meeting_service.aux_service')
    def test_whatsapp_sent_on_new_meeting(self, mock_aux, mock_ai, mock_wa, mock_db):
        from services import meeting_service
        
        # Setup mock data for a registered user
        call_count = {"clients": 0}
        def db_side_effect(query, params=None, **kwargs):
            if "FROM users WHERE email =" in query:
                return {"phone": "whatsapp:+917980909430", "timezone": "Asia/Kolkata"}
            if "FROM meetings WHERE outlook_event_id =" in query:
                return None # No existing meeting
            if "FROM clients WHERE email =" in query:
                call_count["clients"] += 1
                if call_count["clients"] == 1:
                    return None # New client check
                return {"id": 1} # After insert
            return None

        mock_db.execute_query.side_effect = db_side_effect
        
        # Mock AI response
        mock_ai.generate_coaching_plan.return_value = {
            "greeting": "Hi Buddha!",
            "scenario": "Robustness Test Meeting",
            "steps": ["Step 1", "Step 2"],
            "recommended_reply": "I am ready."
        }
        
        # Test payload
        payload = {
            "meeting": {
                "id": "new_test_mtg_123",
                "organizer": "bhattacharyabuddhadeb@outlook.com",
                "start": datetime.now().isoformat(),
                "end": (datetime.now() + timedelta(minutes=30)).isoformat(),
                "title": "Fresh Test Meeting",
                "online_meeting_url": "https://zoom.us/j/999888777"
            },
            "client": {
                "email": "client@test.com",
                "name": "Test Client"
            }
        }
        
        # Call the function
        print("\n--- Simulating process_outlook_webhook ---")
        try:
            meeting_service.process_outlook_webhook(payload)
        except Exception as e:
            import traceback
            with open("error_traceback.txt", "w") as f:
                f.write(traceback.format_exc())
            traceback.print_exc()
            raise e
        
        # Verify WhatsApp was sent
        print(f"WhatsApp mocked call count: {mock_wa.send_whatsapp_message.call_count}")
        self.assertTrue(mock_wa.send_whatsapp_message.called)
        
        # Verify Bot was scheduled
        print(f"Bot Join mocked call count: {mock_aux.schedule_meeting.call_count}")
        self.assertTrue(mock_aux.schedule_meeting.called)
        
        print("PASSED: WhatsApp and Bot Join both triggered correctly.")

if __name__ == '__main__':
    unittest.main()
