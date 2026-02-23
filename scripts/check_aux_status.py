from database import db
from services import aux_service
import json

def check_aux_status():
    res = db.execute_query("SELECT id, title, aux_meeting_id, aux_meeting_token, start_time FROM meetings WHERE aux_meeting_token IS NOT NULL AND status IN ('scheduled', 'reminder_sent') ORDER BY id DESC LIMIT 10", fetch_all=True)
    
    if not res:
        print("No pending Aux meetings found in DB.")
        return

    print(f"{'ID':<5} | {'Title':<20} | {'Start':<20} | {'Aux Status'}")
    print("-" * 70)
    for r in res:
        token = r['aux_meeting_token']
        try:
            status_data = aux_service.get_meeting_status(token)
            if status_data:
                aux_status = status_data.get("status", "unknown")
            else:
                aux_status = "FETCH_FAILED"
        except Exception as e:
            aux_status = f"ERROR: {e}"
            
        print(f"{r['id']:<5} | {str(r['title']):<20} | {str(r['start_time']):<20} | {aux_status}")

if __name__ == "__main__":
    check_aux_status()
