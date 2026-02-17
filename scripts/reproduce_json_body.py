import sys
import os
import json
import logging

# Setup Path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock Logging
logging.basicConfig(level=logging.INFO)

# Mock DB and AI
from services import meeting_service, ai_service
from database import db

# Mock the AI service to see what it receives
def mock_generate_coaching_plan(meeting_title, client_name, client_company, start_time, meeting_body="", location=""):
    print(f"\n[MOCK AI] Received Inputs:")
    print(f"  Title: {meeting_title}")
    print(f"  Body (First 100 chars): {meeting_body[:100]}...")
    print(f"  Location: {location}")
    
    # Check if body is clean text or raw JSON
    if '{"contentType":"html"' in meeting_body:
        print("❌ FAILURE: Body is still raw JSON string!")
    else:
        print("✅ SUCCESS: Body appears to be parsed/cleaned.")
        
    return {"greeting": "Hi", "scenario": "Test", "steps": [], "recommended_reply": "Ok"}

ai_service.generate_coaching_plan = mock_generate_coaching_plan

def test_json_body_payload():
    print("🚀 Testing JSON Body Payload processing...")
    
    # Mock specific payload from user logs
    # Note: 'body' is a JSON string inside the dict
    raw_body_content = json.dumps({
        "contentType": "html",
        "content": "<html>\r\n<head>\r\n<meta http-equiv=\"Content-Type\" content=\"text/html; charset=utf-8\">\r\n</head>\r\n<body>\r\n<div style=\"font-family:Aptos,Aptos_EmbeddedFont,Aptos_MSFontService,Calibri,Helvetica,sans-serif; font-size:12pt; color:rgb(0,0,0)\">\r\nThis meeting is scheduled to conduct a complete end-to-end functional test of the CoachLink360 platform.</div>\r\n</body>\r\n</html>"
    })
    
    payload = {
        "meeting": {
            "title": "CoachLink360 – End-to-End System Test",
            "body": raw_body_content,
            "location": {'display_name': 'Microsoft Teams Meeting'},
            "start_time": "2026-02-11T07:05:00.000Z",
            "end_time": "2026-02-11T07:35:00.000Z",
            "organizer": {'name': 'Rahul', 'address': 'rahulbhattacharya0131@outlook.com'}
        },
        "client": {
            "email": "client@test.com"
        }
    }
    
    # Init DB (mocking)
    db.init_db()
    
    # Ensure user exists
    db.execute_query("INSERT OR IGNORE INTO users (email, name, phone) VALUES (?, ?, ?)", 
                     ("rahulbhattacharya0131@outlook.com", "Rahul", "+917980909430"), commit=True)
    
    # Run processing
    try:
        meeting_service.process_outlook_webhook(payload)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_json_body_payload()
