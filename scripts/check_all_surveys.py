"""
Fetch all survey data with increased limit to catch any new surveys
"""
import requests
import json
from datetime import datetime

SURVEY_API_URL = "https://projects.aux-rolplay.com/coachlink360/api/admin/responses"

# Fetch more surveys to catch the newest one
response = requests.get(SURVEY_API_URL, params={"limit": 100}, timeout=10)

if response.status_code == 200:
    data = response.json()
    
    print("=" * 80)
    print(f"COMPLETE SURVEY LIST (Total: {data.get('total')})")
    print("=" * 80)
    
    if data.get('results'):
        # Sort by submission date (most recent first)
        surveys = sorted(data['results'], key=lambda x: x.get('submitted_at', ''), reverse=True)
        
        for i, survey in enumerate(surveys, 1):
            print(f"\n{'🆕 ' if i == 1 else ''}Survey #{i} (ID: {survey.get('id')})")
            print(f"Submitted: {survey.get('submitted_at')}")
            print(f"Participant: {survey.get('participant_name')} <{survey.get('participant_email')}>")
            print(f"Meeting: {survey.get('meeting_title')} (ID: {survey.get('meeting_id')})")
            
            avg = sum([
                survey.get('punctuality', 0),
                survey.get('listening_understanding', 0),
                survey.get('knowledge_expertise', 0),
                survey.get('clarity_answers', 0),
                survey.get('overall_value', 0)
            ]) / 5
            print(f"Average Rating: {avg:.1f}/5")
            
            if survey.get('most_valuable'):
                print(f"Most Valuable: {survey.get('most_valuable')[:50]}...")
            if survey.get('improvements'):
                print(f"Improvements: {survey.get('improvements')[:50]}...")
            print("-" * 80)
    
    print(f"\n\n📄 Full data:")
    print(json.dumps(data, indent=2))
else:
    print(f"Error: {response.status_code}")
    print(response.text)
