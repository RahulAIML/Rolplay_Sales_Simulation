import os
import sys

# Add project root to path
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root)

from database import db

def list_last_meetings():
    res = db.execute_query("SELECT id, title, start_time, status, aux_meeting_id FROM meetings ORDER BY id DESC LIMIT 5", fetch_all=True)
    if res:
        for r in res:
            print(f"ID: {r['id']} | Title: {r['title']} | Start: {r['start_time']} | Status: {r['status']}")
    else:
        print("No meetings found")

if __name__ == "__main__":
    list_last_meetings()
