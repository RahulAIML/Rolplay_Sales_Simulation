from database import db
import re

def analyze_meetings():
    res = db.execute_query("SELECT id, title, location, summary, aux_meeting_id FROM meetings ORDER BY id DESC LIMIT 20", fetch_all=True)
    
    link_pattern = r"(https?://(?:[a-zA-Z0-9-]+\.)?(?:zoom\.us|meet\.google\.com|teams\.(?:live|microsoft)\.com|teams\.microsoft\.com/l/meetup-join)/[^\s\"<>]+)"
    
    print(f"Analyzing last 20 meetings:\n")
    for r in res:
        mid = r['id']
        title = r['title']
        loc = r['location'] or ""
        summ = r['summary'] or ""
        aux_id = r['aux_meeting_id']
        
        combined = f"{loc} {summ}"
        match = re.search(link_pattern, combined)
        link = match.group(1) if match else None
        
        status = "✅ Scheduled" if aux_id else "❌ NOT Scheduled"
        if not link:
            status = "⚪ No Link Found"
            
        print(f"ID: {mid} | Title: {title}")
        print(f"  Status: {status}")
        print(f"  Aux ID: {aux_id}")
        if link:
            print(f"  Link: {link}")
        else:
            # Print a bit of location/summary to see what's there
            print(f"  Loc: {loc[:50]}...")
            print(f"  Summ: {summ[:50]}...")
        print("-" * 30)

if __name__ == "__main__":
    analyze_meetings()
