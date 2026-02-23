import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Mock database and other services before importing meeting_service
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class TestWebhookTimezone(unittest.TestCase):
    @patch('services.meeting_service.db')
    @patch('services.meeting_service.whatsapp_service')
    @patch('services.meeting_service.ai_service')
    @patch('services.meeting_service.aux_service')
    def test_outlook_webhook_timezone(self, mock_aux, mock_ai, mock_wa, mock_db):
        from services import meeting_service
        
        # Setup mock data
        def db_side_effect(query, params=None, **kwargs):
            if "FROM users" in query:
                return {"phone": "whatsapp:+1234567890", "timezone": "Asia/Kolkata"}
            if "FROM clients" in query:
                return {"id": 1}
            return None

        mock_db.execute_query.side_effect = db_side_effect
        
        # Test payload
        payload = {
            "meeting": {
                "id": "test_id",
                "organizer": "user@example.com",
                "start": "2026-02-23T14:00:00Z", # UTC
                "end": "2026-02-23T14:30:00Z",
                "title": "Test Meeting",
                "online_meeting_url": "https://zoom.us/j/123456789"
            }
        }
        
        # Mock AI response to avoid errors
        mock_ai.generate_coaching_plan.return_value = {
            "greeting": "Hi", "scenario": "Test", "steps": ["Step 1"], "recommended_reply": "Reply"
        }
        
        # Call the function
        meeting_service.process_outlook_webhook(payload)
        
        # Verify aux_service.schedule_meeting call
        # 14:00 UTC should be 19:30 IST (Asia/Kolkata)
        expected_time = "2026-02-23T19:30:00"
        
        mock_aux.schedule_meeting.assert_called_once()
        args, kwargs = mock_aux.schedule_meeting.call_args
        self.assertEqual(args[1], expected_time)
        print(f"PASSED: Scheduled time {args[1]} matches expected local naive time {expected_time}")

if __name__ == '__main__':
    unittest.main()
