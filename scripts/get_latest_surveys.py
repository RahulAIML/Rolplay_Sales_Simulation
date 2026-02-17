"""
Save all survey data to timestamped file
"""
import requests
import json
from datetime import datetime

SURVEY_API_URL = "https://projects.aux-rolplay.com/coachlink360/api/admin/responses"

response = requests.get(SURVEY_API_URL, params={"limit": 100}, timeout=10)

if response.status_code == 200:
    data = response.json()
    
    # Save to timestamped file
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"all_surveys_{timestamp}.json"
    
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Full data saved to: {filename}")
    print(f"\nTotal surveys: {data.get('total')}")
    print(f"Fetched: {len(data.get('results', []))} surveys\n")
    
    if data.get('results'):
        # Sort by ID (highest = newest)
        surveys = sorted(data['results'], key=lambda x: x.get('id', 0), reverse=True)
        
        print("=" * 80)
        print("ALL SURVEYS (Newest First):")
        print("=" * 80)
        
        for i, survey in enumerate(surveys, 1):
            print(f"\n{i}. Survey ID: {survey.get('id')} {'🆕 NEWEST' if i == 1 else ''}")
            print(f"   Submitted: {survey.get('submitted_at')}")
            print(f"   Participant: {survey.get('participant_email')}")
            print(f"   Meeting: {survey.get('meeting_title')}")
            print(f"   Meeting ID: {survey.get('meeting_id')}")
        
        print("\n" + "=" * 80)
        print(f"📄 Complete JSON saved to: {filename}")
else:
    print(f"Error: {response.status_code}")
