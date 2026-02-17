"""
Test script to fetch survey responses from the CoachLink360 API
and inspect the data structure.
"""
import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()

# Survey API endpoint
SURVEY_API_URL = "https://projects.aux-rolplay.com/coachlink360/api/admin/responses"

# Get admin token from environment (if needed)
ADMIN_TOKEN = os.getenv("SURVEY_ADMIN_TOKEN", "")

def fetch_survey_responses():
    """Fetch survey responses from the API"""
    
    headers = {}
    if ADMIN_TOKEN:
        headers["x-admin-token"] = ADMIN_TOKEN
    
    params = {
        "limit": 5  # Just fetch 5 for testing
    }
    
    try:
        print(f"Fetching from: {SURVEY_API_URL}")
        print(f"Using admin token: {'Yes' if ADMIN_TOKEN else 'No'}")
        print("-" * 60)
        
        response = requests.get(SURVEY_API_URL, headers=headers, params=params, timeout=10)
        
        print(f"Status Code: {response.status_code}")
        print("-" * 60)
        
        if response.status_code == 200:
            data = response.json()
            print("✅ SUCCESS! Here's the response structure:\n")
            print(json.dumps(data, indent=2))
            
            # Show what fields are available
            if data.get("results") and len(data["results"]) > 0:
                print("\n" + "=" * 60)
                print("SAMPLE RESPONSE OBJECT (first result):")
                print("=" * 60)
                print(json.dumps(data["results"][0], indent=2))
                
                print("\n" + "=" * 60)
                print("AVAILABLE FIELDS:")
                print("=" * 60)
                for key in data["results"][0].keys():
                    print(f"  - {key}")
            
            return data
            
        elif response.status_code == 401:
            print("❌ Unauthorized - Need admin token!")
            print("\nAdd SURVEY_ADMIN_TOKEN to your .env file")
            return None
            
        else:
            print(f"❌ Error: {response.status_code}")
            print(response.text)
            return None
            
    except Exception as e:
        print(f"❌ Exception: {e}")
        return None

if __name__ == "__main__":
    fetch_survey_responses()
