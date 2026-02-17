"""
Fetch survey data and save to file for inspection
"""
import requests
import json
from datetime import datetime

SURVEY_API_URL = "https://projects.aux-rolplay.com/coachlink360/api/admin/responses"

response = requests.get(SURVEY_API_URL, params={"limit": 50}, timeout=10)

if response.status_code == 200:
    data = response.json()
    
    # Save to file
    filename = f"survey_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Saved full data to: {filename}")
    print(f"\nTotal surveys in database: {data.get('total')}")
    print(f"Fetched: {len(data.get('results', []))} surveys")
    
    if data.get('results'):
        print("\n" + "=" * 80)
        print("SURVEY SUMMARY:")
        print("=" * 80)
        
        for i, survey in enumerate(data['results'], 1):
            avg_rating = (
                survey.get('punctuality', 0) +
                survey.get('listening_understanding', 0) +
                survey.get('knowledge_expertise', 0) +
                survey.get('clarity_answers', 0) +
                survey.get('overall_value', 0)
            ) / 5
            
            print(f"\n{i}. Survey ID: {survey.get('id')}")
            print(f"   Participant: {survey.get('participant_name')} <{survey.get('participant_email')}>")
            print(f"   Meeting: {survey.get('meeting_title')} (ID: {survey.get('meeting_id')})")
            print(f"   Submitted: {survey.get('submitted_at')}")
            print(f"   Average Rating: {avg_rating:.1f}/5 ⭐")
            
        print("\n" + "=" * 80)
        print(f"\n📄 Full JSON details saved to: {filename}")
    else:
        print("\nNo survey responses found.")
else:
    print(f"❌ Error: Status {response.status_code}")
    print(response.text)
