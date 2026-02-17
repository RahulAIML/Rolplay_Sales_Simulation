import requests
import json
import time

# Configuration
BASE_URL = "https://rolplay-sales-simulation-parh.onrender.com"
ENDPOINT = "/api/ingest-raw-meeting"

def test_flow(user_email):
    print(f"--- Testing Live Flow ---")
    print(f"Targeting User Email: {user_email}")
    print(f"URL: {BASE_URL}{ENDPOINT}")
    
    # 1. Construct Payload
    # We include 'owner: <email>' so the server finds YOUR phone number in the DB.
    raw_text = f"""
    session_id: test_live_{int(time.time())}
    owner: {user_email}
    
    Summary:
    This is a test meeting to verify the live Twilio connection. 
    The system should parse this and send a WhatsApp notification.
    
    Sales Rep: Hello client, thanks for joining.
    Client: I am worried about the price.
    Sales Rep: I understand, let me explain the value.
    """
    
    payload = {
        "raw_text": raw_text
    }
    
    # 2. Send Request
    try:
        print("Sending webhook data...")
        resp = requests.post(f"{BASE_URL}{ENDPOINT}", json=payload)
        
        print(f"Status Code: {resp.status_code}")
        try:
            print(f"Response: {json.dumps(resp.json(), indent=2)}")
        except:
            print(f"Response: {resp.text}")
        
        if resp.status_code == 200:
            print("\n✅ Webhook sent successfully!")
            print("👉 Check your WhatsApp now.")
            print("(If you don't receive it, ensure you sent 'Hi' to the bot first, or check Render logs).")
        else:
            print("\n❌ Failed. Check server logs on Render.")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    print("This script simulates a meeting finishing and sending data to your App.")
    email = input("Enter your registered email (used in /setup): ").strip()
    if email:
        test_flow(email)
    else:
        print("Email is required to find your user.")
