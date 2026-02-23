from database import db
import datetime

def list_meetings():
    res = db.execute_query("SELECT id, title, start_time, status, aux_meeting_id FROM meetings ORDER BY id DESC LIMIT 20", fetch_all=True)
    print(f"{'ID':<5} | {'Title':<25} | {'Start Time':<25} | {'Status':<15} | {'AuxID':<10}")
    print("-" * 90)
    for r in res:
        print(f"{r['id']:<5} | {str(r['title']):<25} | {str(r['start_time']):<25} | {str(r['status']):<15} | {str(r['aux_meeting_id']):<10}")

if __name__ == "__main__":
    list_meetings()
