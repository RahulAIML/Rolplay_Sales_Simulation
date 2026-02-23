from database import db
import re

def check_recent_meetings():
    res = db.execute_query("SELECT id, title, location, summary, aux_meeting_id, outlook_event_id FROM meetings ORDER BY id DESC LIMIT 10", fetch_all=True)
    
    link_pattern = r"(https?://(?:[a-zA-Z0-9-]+\.)?(?:zoom\.us|meet\.google\.com|teams\.(?:live|microsoft)\.com|teams\.microsoft\.com/l/meetup-join)/[^\s\"<>]+)"
    
    for r in res:
        mtg_id = r['id']
        title = r['title']
        location = r['location'] or ""
        summary = r['summary'] or ""
        aux_id = r['aux_meeting_id']
        
        combined = f"{location} {summary}"
        match = re.search(link_pattern, combined)
        link = match.group(1) if match else None
        
        print(f"ID: {mtg_id} | Title: {title}")
        print(f"  Link found in DB fields: {link is not None}")
        print(f"  Aux ID in DB: {aux_id}")
        if link and not aux_id:
            print(f"  ⚠️ ALERT: Link exists but Aux ID is NULL!")
        print("-" * 40)

if __name__ == "__main__":
    check_recent_meetings()
