import requests
import json
import datetime

def simulate_webhook():
    url = "http://localhost:5000/outlook-webhook"
    
    # Needs a registered user email. I'll check the DB first to find one.
    # For now, I'll assume there's a user.
    
    payload = {
        "meeting": {
            "title": "Bot Join Test Meeting",
            "start_time": (datetime.datetime.now() + datetime.timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_time": (datetime.datetime.now() + datetime.timedelta(minutes=40)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "organizer": {"email": "test@example.com"},
            "meeting_id": "test_event_123",
            "location": "Online",
            "body": "Join here: https://meet.google.com/abc-defg-hij"
        },
        "client": {
            "name": "John Doe",
            "email": "john@example.com",
            "company": "Test Co"
        }
    }
    
    # I need to know a valid registered email to test this properly.
    # I'll find one from the DB.
    from database import db
    user = db.execute_query("SELECT email FROM users LIMIT 1", fetch_one=True)
    if user:
        payload["meeting"]["organizer"]["email"] = user["email"]
        print(f"Using registered user: {user['email']}")
    else:
        print("No users found in DB. Registration might be needed first.")
        return

    print(f"Sending payload to {url}...")
    try:
        # We need the app running to test this way, or we call the service function directly.
        # Calling service function is easier.
        from services import meeting_service
        result = meeting_service.process_outlook_webhook(payload)
        print(f"Result: {result}")
        
        # Check if the meeting was saved with Aux ID
        mtg = db.execute_query("SELECT aux_meeting_id FROM meetings WHERE outlook_event_id = 'test_event_123'", fetch_one=True)
        print(f"Saved Aux ID: {mtg['aux_meeting_id'] if mtg else 'MTG NOT FOUND'}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    simulate_webhook()
