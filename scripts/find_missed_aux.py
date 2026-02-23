from database import db
import re

def check_missing_aux():
    res = db.execute_query("SELECT id, title, location, summary, aux_meeting_id FROM meetings WHERE aux_meeting_id IS NULL ORDER BY id DESC LIMIT 20", fetch_all=True)
    
    link_pattern = r"(https?://(?:[a-zA-Z0-9-]+\.)?(?:zoom\.us|meet\.google\.com|teams\.(?:live|microsoft)\.com|teams\.microsoft\.com/l/meetup-join)/[^\s\"<>]+)"
    
    print(f"Checking meetings without Aux ID:\n")
    for r in res:
        mid = r['id']
        title = r['title']
        loc = r['location'] or ""
        summ = r['summary'] or ""
        
        combined = f"{loc} {summ}"
        match = re.search(link_pattern, combined)
        link = match.group(1) if match else None
        
        if link:
            print(f"ID: {mid} | Title: {title}")
            print(f"  ⚠️ LINK FOUND BUT NO AUX ID!")
            print(f"  Link: {link}")
            print("-" * 30)
        else:
            # print(f"ID: {mid} | Title: {title} | No link found")
            pass

if __name__ == "__main__":
    check_missing_aux()
