import requests
import json
import datetime
import logging

# Enable logging to see what's happening
logging.basicConfig(level=logging.INFO)

def simulate_webhook():
    from database import db
    from services import meeting_service
    
    url = "http://localhost:5000/outlook-webhook"
    
    # Try to find a real user in the DB
    user = db.execute_query("SELECT email FROM users LIMIT 1", fetch_one=True)
    if not user:
        print("No users found. Creating a test user...")
        db.execute_query("INSERT INTO users (email, name, phone, timezone) VALUES (?, ?, ?, ?)", 
                         ("test@example.com", "Test User", "+1234567890", "UTC"), commit=True)
        user = {"email": "test@example.com"}

    payload = {
        "meeting": {
            "title": "Debug Bot Join",
            "start_time": (datetime.datetime.now() + datetime.timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_time": (datetime.datetime.now() + datetime.timedelta(minutes=45)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "organizer": {"email": user["email"]},
            "meeting_id": f"event_{int(datetime.datetime.now().timestamp())}",
            "location": "Online Meeting",
            "body": "Join link: https://meet.google.com/abc-defg-hij"
        },
        "client": {
            "name": "Jane Doe",
            "email": "jane@example.com"
        }
    }
    
    print(f"Sending payload to meeting_service...")
    try:
        result = meeting_service.process_outlook_webhook(payload)
        print(f"Result: {result}")
        
        # Check DB
        mtg = db.execute_query("SELECT aux_meeting_id FROM meetings WHERE outlook_event_id = ?", (payload["meeting"]["meeting_id"],), fetch_one=True)
        print(f"Saved Aux ID: {mtg['aux_meeting_id'] if mtg else 'NOT FOUND'}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    simulate_webhook()
