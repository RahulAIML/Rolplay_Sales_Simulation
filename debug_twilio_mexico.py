import os
import logging
from twilio.rest import Client
from dotenv import load_dotenv

# Load env vars
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)

def test_send(to_number):
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    from_num = os.getenv("TWILIO_WHATSAPP_FROM")

    print(f"--- Debugging Twilio ---")
    print(f"SID: {sid[:5]}..." if sid else "SID: Missing")
    print(f"From: {from_num}")
    print(f"To: {to_number}")

    if not all([sid, token, from_num]):
        print("ERROR: Missing credentials.")
        return

    try:
        client = Client(sid, token)
        msg = client.messages.create(
            from_=from_num,
            body="Test message from debug script. Please ignore.",
            to=to_number
        )
        print(f"SUCCESS: Message sent. SID: {msg.sid}")
        print(f"Status: {msg.status}")
        if msg.error_message:
            print(f"Error Message: {msg.error_message}")
        if msg.error_code:
            print(f"Error Code: {msg.error_code}")
            
    except Exception as e:
        print(f"FAILED: {e}")

if __name__ == "__main__":
    # Prompt user for the number they are trying to fix
    target = input("Enter the +52 number (e.g. whatsapp:+521...): ").strip()
    if not target.startswith("whatsapp:"):
        target = f"whatsapp:{target}"
    
    test_send(target)
