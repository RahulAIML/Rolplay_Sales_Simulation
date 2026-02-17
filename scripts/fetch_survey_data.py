"""
Enhanced survey API fetcher - Shows full data
"""
import requests
import json

SURVEY_API_URL = "https://projects.aux-rolplay.com/coachlink360/api/admin/responses"

response = requests.get(SURVEY_API_URL, params={"limit": 10}, timeout=10)

if response.status_code == 200:
    data = response.json()
    
    print("=" * 80)
    print(f"SURVEY API RESPONSE")
    print("=" * 80)
    print(f"Total surveys: {data.get('total')}")
    print(f"Page: {data.get('page')}")
    print(f"Limit: {data.get('limit')}")
    print(f"Results count: {len(data.get('results', []))}")
    print("=" * 80)
    
    if data.get('results'):
        print("\nSURVEY RESPONSES:\n")
        for i, survey in enumerate(data['results'], 1):
            print(f"--- Survey #{i} (ID: {survey.get('id')}) ---")
            print(f"Participant: {survey.get('participant_name')} ({survey.get('participant_email')})")
            print(f"Meeting: {survey.get('meeting_title')}")
            print(f"Meeting ID: {survey.get('meeting_id')}")
            print(f"Submitted: {survey.get('submitted_at')}")
            print(f"\nRatings:")
            print(f"  ⏰ Punctuality: {survey.get('punctuality')}/5")
            print(f"  👂 Listening: {survey.get('listening_understanding')}/5")
            print(f"  🎓 Knowledge: {survey.get('knowledge_expertise')}/5")
            print(f"  💬 Clarity: {survey.get('clarity_answers')}/5")
            print(f"  ✨ Overall: {survey.get('overall_value')}/5")
            
            if survey.get('most_valuable'):
                print(f"\nMost Valuable: {survey.get('most_valuable')}")
            if survey.get('improvements'):
                print(f"Improvements: {survey.get('improvements')}")
            
            print("\n" + "-" * 80 + "\n")
    else:
        print("\nNo survey responses found.")
        
    print("\n\nFULL JSON DATA:")
    print(json.dumps(data, indent=2))
else:
    print(f"Error: Status {response.status_code}")
    print(response.text)
