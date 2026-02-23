import os
import sys

# Add project root to path
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root)

from database import db

def check_link(mid):
    m = db.execute_query("SELECT id, title, location, summary, aux_meeting_id FROM meetings WHERE id = ?", (mid,), fetch_one=True)
    if m:
        print(f"ID: {m['id']}")
        print(f"Title: {m['title']}")
        print(f"Location: {m['location']}")
        print(f"Summary: {m['summary'][:200]}...")
        
        from services import meeting_service
        search_text = f"{m['location']} {m['summary']}"
        link = meeting_service._extract_meeting_link(search_text)
        print(f"Extracted Link: {link}")
    else:
        print("Meeting not found")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        check_link(sys.argv[1])
    else:
        # Check meeting 33
        check_link(33)
