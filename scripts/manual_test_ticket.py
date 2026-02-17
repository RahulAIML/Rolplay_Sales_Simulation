import os
import sys
from hubspot import HubSpot
from hubspot.crm.objects import SimplePublicObjectInputForCreate
from dotenv import load_dotenv

# Load env vars from root directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

def test_create_ticket():
    token = os.getenv("HUBSPOT_ACCESS_TOKEN")
    if not token:
        print("❌ Error: HUBSPOT_ACCESS_TOKEN not found in .env")
        return

    print(f"Attempting to create a test Ticket with token: {token[:4]}...")

    try:
        api_client = HubSpot(access_token=token)
        
        properties = {
            "subject": "Test Ticket from Agent Verification",
            "content": "This is a test ticket to verify API write access.",
            "hs_pipeline_stage": "1", 
            "hs_pipeline": "0",
            "hs_ticket_priority": "LOW"
        }
        
        ticket_input = SimplePublicObjectInputForCreate(properties=properties)
        result = api_client.crm.tickets.basic_api.create(simple_public_object_input_for_create=ticket_input)
        
        print(f"✅ SUCCESS: Ticket created!")
        print(f"   - Ticket ID: {result.id}")
        print(f"   - Subject: {result.properties['subject']}")
        
    except Exception as e:
        print(f"❌ TICKET CREATION FAILED: {e}")

if __name__ == "__main__":
    test_create_ticket()
