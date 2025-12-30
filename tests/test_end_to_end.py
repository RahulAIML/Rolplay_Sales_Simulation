import unittest
from unittest.mock import patch, MagicMock
import json
import os
import sys

# Add root to sys.path to import app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from database import db

class TestEndToEnd(unittest.TestCase):
    
    def setUp(self):
        # Configure Test DB (In-Memory SQLite)
        self.app = app.test_client()
        self.app.testing = True
        
        # Override DB connection to use memory or temp file
        # Since DBHandler singleton is already initialized, we might need a way to swap it.
        # For simplicity in this structure, we'll just use a test db file.
        self.test_db = "test_coachlink.db"
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
            
        # Patch the connection logic or just set env var?
        # The DBHandler reads env vars at init. 
        # Easier to just monkeypatch the singleton's get_connection method or the filename.
        
        # Re-initialize DB tables on the test file
        # We need to hack the global 'db' instance to use our test file
        db.is_postgres = False
        
        # Define a test connector
        import sqlite3
        def test_connect():
            conn = sqlite3.connect(self.test_db, timeout=30.0)
            conn.row_factory = sqlite3.Row
            return conn
            
        db.get_connection = test_connect
        db.init_db()

    def tearDown(self):
        if os.path.exists(self.test_db):
            try:
                os.remove(self.test_db)
            except:
                pass

    @patch('services.whatsapp_service.send_whatsapp_message')
    def test_01_user_registration(self, mock_send_whatsapp):
        """Test User Registration Flow"""
        mock_send_whatsapp.return_value = "msg_123"
        
        payload = {
            "name": "Test User",
            "email": "test@user.com",
            "phone": "+1 555-0100"
        }
        
        response = self.app.post('/register', data=payload)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Test User is registered", response.data)
        
        # Verify DB
        user = db.execute_query("SELECT * FROM users WHERE email='test@user.com'", fetch_one=True)
        self.assertIsNotNone(user)
        self.assertEqual(user['phone'], "whatsapp:+15550100")
        
        # Verify Welcome Message
        mock_send_whatsapp.assert_called_once()
        args, kwargs = mock_send_whatsapp.call_args
        self.assertEqual(args[0], "whatsapp:+15550100")

    @patch('services.ai_service.generate_coaching_plan')
    @patch('services.whatsapp_service.send_whatsapp_message')
    def test_02_outlook_webhook_flow(self, mock_send_whatsapp, mock_ai_plan):
        """Test Meeting Ingestion -> AI -> WhatsApp"""
        
        # 1. Pre-register User (Dependency)
        db.execute_query("INSERT INTO users (email, name, phone) VALUES (?, ?, ?)", 
                         ("organizer@company.com", "Boss", "whatsapp:+15559999"), commit=True)
        
        # 2. Mock AI
        mock_ai_plan.return_value = {
            "greeting": "Hi Boss",
            "scenario": "Negotiation",
            "steps": ["Step 1", "Step 2"],
            "recommended_reply": "Got it"
        }
        
        # 3. Webhook Payload
        payload = {
            "meeting": {
                "title": "Big Deal",
                "start_time": "2025-12-30T10:00:00Z",
                "end_time": "2025-12-30T10:30:00Z",
                "organizer": {"address": "organizer@company.com"},
                "meeting_id": "evt_unique_1"
            },
            "client": {
                "name": "Moneybags",
                "email": "client@rich.com",
                "company": "Rich Corp"
            }
        }
        
        response = self.app.post('/outlook-webhook', json=payload)
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['status'], 'success')
        
        # Verify DB
        mtg = db.execute_query("SELECT * FROM meetings WHERE outlook_event_id='evt_unique_1'", fetch_one=True)
        self.assertIsNotNone(mtg)
        self.assertEqual(mtg['status'], 'scheduled')
        
        # Verify AI called
        mock_ai_plan.assert_called_once()
        
        # Verify WhatsApp sent
        mock_send_whatsapp.assert_called_once()
        # Check recipient
        args, _ = mock_send_whatsapp.call_args
        self.assertEqual(args[0], "whatsapp:+15559999")

    @patch('services.hubspot_service.sync_note_to_contact')
    def test_03_whatsapp_reply_done(self, mock_hs_sync):
        """Test 'Done' command syncs to HubSpot"""
        
        # 1. Setup Data
        db.execute_query("INSERT INTO clients (name, email) VALUES (?, ?)", ("Sync Client", "sync@c.com"), commit=True)
        client = db.execute_query("SELECT id FROM clients WHERE email='sync@c.com'", fetch_one=True)
        client_id = client['id']
        
        db.execute_query(
            "INSERT INTO meetings (client_id, salesperson_phone, status, outlook_event_id) VALUES (?, ?, 'scheduled', 'evt_2')",
            (client_id, "whatsapp:+15559999"),
            commit=True
        )
        
        mtg = db.execute_query("SELECT * FROM meetings WHERE outlook_event_id='evt_2'", fetch_one=True)
        mtg_id = mtg['id']
        
        # 2. Simulate Webhook
        payload = {
            'From': 'whatsapp:+15559999',
            'Body': 'Done! Great call.'
        }
        response = self.app.post('/whatsapp-webhook', data=payload)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"marked as completed", response.data)
        
        # 3. Verify DB Update
        updated = db.execute_query("SELECT status FROM meetings WHERE id=?", (mtg_id,), fetch_one=True)
        self.assertEqual(updated['status'], 'completed')
        
        # 4. Verify HubSpot Sync
        mock_hs_sync.assert_called_once()
        args, _ = mock_hs_sync.call_args
        self.assertEqual(args[0], 1) # Client ID
        self.assertIn("Great call", args[1]) # Note body

    @patch('services.ai_service.generate_coaching_plan')
    @patch('services.whatsapp_service.send_whatsapp_message')
    def test_integration_new_json_structure(self, mock_send_whatsapp, mock_ai_plan):
        """Test with the specific JSON structure provided by the user"""
        
        # Mock returns
        mock_ai_plan.return_value = {"greeting": "Hi", "scenario": "Test", "steps": [], "recommended_reply": "Ok"}
        mock_send_whatsapp.return_value = "msg_id"

        from datetime import datetime, timedelta
        
        # Exact payload structure from user
        payload = {
            "meeting": {
                "meeting_id": "new_struct_1",
                "title": "Structure Test",
                "start_time": (datetime.now() + timedelta(hours=1)).isoformat(),
                "end_time": (datetime.now() + timedelta(hours=2)).isoformat(),
                "organizer": {
                    "name": "Integration User",
                    "email": "test_struct@user.com"
                }
            },
            "client": {
                "first_name": "John",
                "last_name": "Doe",
                "email": "johndoe_struct@test.com",
                "phone": "+1234567890",
                "company": "Deepmind"
            }
        }
        
        from services.meeting_service import process_outlook_webhook
        
        # 1. Ensure user exists (Organizer)
        db.execute_query("INSERT INTO users (name, email, phone) VALUES (?, ?, ?)", 
                        ("Integration User", "test_struct@user.com", "whatsapp:+15550000"), commit=True)
        
        # 2. Process
        res = process_outlook_webhook(payload)
        self.assertEqual(res['status'], 'success')
        
        # 3. Verify Client Name Combination (John + Doe = John Doe)
        client = db.execute_query("SELECT name FROM clients WHERE email='johndoe_struct@test.com'", fetch_one=True)
        self.assertEqual(client['name'], "John Doe")

    @patch('services.ai_service.generate_coaching_plan')
    @patch('services.whatsapp_service.send_whatsapp_message')
    def test_stringified_organizer_email(self, mock_send_whatsapp, mock_ai_plan):
        """Test parsing when organizer email is a stringified JSON (outlook weirdness)"""
        mock_ai_plan.return_value = {"greeting": "Hi"}
        mock_send_whatsapp.return_value = "msg_id"
        
        from datetime import datetime, timedelta
        import json
        
        # Emulate the weird payload
        real_email = "outlook_alias@outlook.com"
        weird_email_field = json.dumps({"name": "Test User", "address": real_email})
        
        payload = {
            "meeting": {
                "meeting_id": "weird_json_1",
                "title": "Weird JSON Test",
                "start_time": (datetime.now() + timedelta(hours=1)).isoformat(),
                "end_time": (datetime.now() + timedelta(hours=2)).isoformat(),
                "organizer": {
                    "name": "Test User",
                    "email": weird_email_field  # <--- The stringified JSON
                }
            },
            "client": {
                "first_name": "Jane", 
                "last_name": "Doe", 
                "email": "jane@test.com"
            }
        }

        # 1. Register the real email
        db.execute_query("INSERT INTO users (name, email, phone) VALUES (?, ?, ?)", 
                        ("Test JSON User", real_email, "whatsapp:+15551111"), commit=True)

        from services.meeting_service import process_outlook_webhook
        res = process_outlook_webhook(payload)
        
        self.assertEqual(res['status'], 'success')
        # Check if message was sent (means user was found)
        mock_send_whatsapp.assert_called()

    def test_missing_client_graceful_fail(self):
        """Test that missing client data proceeds (200 OK) instead of erroring"""
        
        # Payload with VALID organizer but NO client
        payload = {
            "meeting": { 
                "meeting_id": "no_client_1",
                "title": "No Client Meeting",
                "organizer": {"email": "test_struct@user.com"} # Matches integration user
            }
            # "client" is missing
        }
        
        from services.meeting_service import process_outlook_webhook
        
        # Ensure user exists so we don't get "ignored" due to weak organizer
        # (Re-using 'Integration User' from previous test setup if possible, or insert generic)
        db.execute_query("INSERT OR IGNORE INTO users (name, email, phone) VALUES (?, ?, ?)", 
                        ("Integration User", "test_struct@user.com", "whatsapp:+15550000"), commit=True)

        res = process_outlook_webhook(payload)
        
        # Should now be success (200 implied if not tuple returned, wait, the function returns a dict usually? 
        # Actually my code returns (dict, code).
        # Let's check how I call it: `res = process_outlook_webhook(payload)`
        # If it returns a tuple, res will be a tuple.
        # My previous code returned `{"status":...}, code`.
        
        # Wait, if I call it directly, I get the tuple.
        # If I call via flask client, I get response object.
        # Here I am importing the function and calling it directly.
        
        if isinstance(res, tuple):
            body, code = res
        else:
            body, code = res, 200 # Fallback
            
        self.assertEqual(code, 200)
        # It should process successfully (or be ignored if no start time? defaults generated).
        # It should reach the end.
        self.assertEqual(body.get('status'), 'success')


if __name__ == '__main__':
    unittest.main()
