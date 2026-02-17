import os
import sys
from hubspot import HubSpot
from hubspot.crm.tickets import PublicObjectSearchRequest
from dotenv import load_dotenv

# Load env vars from root directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

def verify_connection():
    token = os.getenv("HUBSPOT_ACCESS_TOKEN")
    if not token:
        print("❌ Error: HUBSPOT_ACCESS_TOKEN not found in .env")
        return

    print(f"Testing HubSpot TICKET Connection with token: {token[:4]}...{token[-4:]}")

    try:
        api_client = HubSpot(access_token=token)
        # Try a simple search to verify tickets scope
        search_req = PublicObjectSearchRequest(limit=1)
        api_client.crm.tickets.search_api.do_search(public_object_search_request=search_req)
        
        print("✅ SUCCESS: Connection established!")
        print("   - Token is valid.")
        print("   - 'tickets' read scope is active.")
        
    except Exception as e:
        print(f"❌ CONNECTION FAILED: {e}")
        print("\nTroubleshooting:")
        print("1. Check if the token is copied correctly.")
        print("2. Ensure the Private App has 'tickets' (Read/Write) scope.")

if __name__ == "__main__":
    verify_connection()
