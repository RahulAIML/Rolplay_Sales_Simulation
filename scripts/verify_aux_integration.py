import sys
import os
from datetime import datetime, timedelta

# Add root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from services import meeting_service, aux_service
from database import db
import unittest
from unittest.mock import patch, MagicMock

class TestAuxIntegration(unittest.TestCase):
    @patch('services.aux_service.schedule_meeting')
    @patch('services.whatsapp_service.send_whatsapp_message')
    @patch('services.ai_service.generate_coaching_plan')
    @patch('services.ai_service.generate_post_meeting_analysis')
    @patch('database.db.execute_query')
    def test_meeting_scheduling_with_link(self, mock_db, mock_analysis, mock_ai, mock_wa, mock_aux):
        # Setup
        mock_aux.return_value = {"token": "test-token-123", "meetingId": 999}
        mock_ai.return_value = {"greeting": "Hello", "scenario": "Test", "steps": ["Step 1"]}
        
        # Multiple DB calls in process_outlook_webhook:
        # 1. SELECT phone FROM users WHERE email = ?
        # 2. SELECT id, name, company, hubspot_contact_id FROM clients WHERE email = ?
        # 3. SELECT id FROM meetings WHERE outlook_event_id = ?
        # 4. UPDATE clients ... (if commit=True)
        # 5. INSERT INTO meetings ... (the one we want to check)
        
        mock_db.side_effect = [
            {'phone': '+1234567890'}, # User check
            None,                      # Client check (insert new)
            None,                      # Meeting exists check
            None,                      # Client insert result (if any)
            None                       # HUBspot update/sync results
        ]
        
        sample_webhook = {
            "meeting": {
                "meeting_id": "out-123",
                "title": "Test Aux Meeting",
                "start_time": (datetime.now() + timedelta(hours=1)).isoformat(),
                "end_time": (datetime.now() + timedelta(hours=2)).isoformat(),
                "location": {"display_name": "https://zoom.us/j/123456789"},
                "body": {"content": "Let's meet here: https://zoom.us/j/123456789"},
                "organizer": {"address": "user@example.com"},
                "attendees": [{"EmailAddress": {"Address": "client@example.com", "Name": "Client"}}]
            },
            "client": {"email": "client@example.com", "name": "Client"}
        }
        
        # Test extraction and scheduling
        # We need to capture the calls to db.execute_query inside the function
        with patch('services.meeting_service.db.execute_query') as mock_db_service_call:
            mock_db_service_call.side_effect = [
                {'phone': '+1234567890'}, # User check
                None,                      # Client check (SELECT)
                None,                      # Client insert
                {'id': 100},               # Client insert ID fetch (SELECT id FROM clients)
                None,                      # Meeting exists check (SELECT id FROM meetings)
                None,                      # HubSpot update (UPDATE clients)
                None,                      # Initial Insert INTO meetings (this is the one!)
                None,                      # hubspot summary sync
            ]
            
            with patch('services.hubspot_service.sync_meeting_summary'):
                with patch('services.hubspot_service.create_or_find_contact', return_value="hs-123"):
                    meeting_service.process_outlook_webhook(sample_webhook)
            
            # Verify Aux API was called
            mock_aux.assert_called_once()
            
            # Find the insert call for meetings
            insert_calls = [call for call in mock_db_service_call.call_args_list if "INSERT INTO meetings" in str(call[0][0])]
            self.assertTrue(len(insert_calls) > 0, "INSERT INTO meetings was not called")
            
            args = insert_calls[0][0][1]
            self.assertIn("test-token-123", args)
            self.assertIn(999, args)

    @patch('services.aux_service.get_meeting_status')
    @patch('services.meeting_service.process_transcript_data')
    @patch('database.db.execute_query')
    def test_scheduler_polling(self, mock_db, mock_process, mock_status):
        # Setup
        mock_db.return_value = [
            {'id': 1, 'aux_meeting_token': 'test-token-123', 'status': 'reminder_sent', 'salesperson_phone': '+123', 'client_id': 100}
        ]
        mock_status.return_value = {
            "status": "completed",
            "transcript": {"content": "The deal is done."}
        }
        mock_process.return_value = {"status": "processed"}
        
        from scheduler import check_pending_meetings
        
        with patch('scheduler.db.execute_query', side_effect=[[], mock_db.return_value, None]): # 1st for scheduled, 2nd for aux_meetings, 3rd for update
            check_pending_meetings()
            
            # Verify polling called
            mock_status.assert_called_with('test-token-123')
            # Verify processing called
            mock_process.assert_called()

if __name__ == "__main__":
    unittest.main()
