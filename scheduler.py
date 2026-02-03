import os
import atexit
import logging
from datetime import datetime, timedelta
import pytz
from apscheduler.schedulers.background import BackgroundScheduler

from database import db
from utils import parse_iso_datetime
from services import whatsapp_service

def check_pending_meetings():
    """
    Periodic job to check for finished meetings that need reminders
    and poll for new survey responses.
    Rules:
    - Status is 'scheduled'.
    - Now > EndTime + 1 minute.
    """
    from services import survey_service
    
    now_utc = datetime.now(pytz.utc)
    
    meetings = db.execute_query("SELECT * FROM meetings WHERE status = 'scheduled'", fetch_all=True) or []
    
    for m in meetings:
        try:
            # End Time Parsing
            if m['end_time']:
                end_dt = parse_iso_datetime(m['end_time'])
            else:
                # Fallback if null (shouldn't happen with new logic)
                start_dt = parse_iso_datetime(m['start_time'])
                end_dt = start_dt + timedelta(minutes=30)
            
            # Logic: 1 minute buffer
            if now_utc >= (end_dt + timedelta(minutes=1)):
                target_phone = m['salesperson_phone']
                
                # Check if we should message (Registered Users Only)
                if not target_phone:
                    # Mark processed silently so we don't loop forever
                    db.execute_query("UPDATE meetings SET status = 'reminder_sent' WHERE id = ?", (m['id'],), commit=True)
                    continue

                # Get Client Name
                crow = db.execute_query("SELECT name FROM clients WHERE id = ?", (m['client_id'],), fetch_one=True)
                cname = crow['name'] if crow else "the client"
                
                # Send Reminder
                msg = f"🔔 Meeting with {cname} finished. How did it go? (Reply 'Done' to log to HubSpot)"
                whatsapp_service.send_whatsapp_message(target_phone, msg)
                
                # Update Status
                db.execute_query("UPDATE meetings SET status = 'reminder_sent' WHERE id = ?", (m['id'],), commit=True)
                logging.info(f"Reminder sent for meeting {m['id']}")
                
        except Exception as e:
            logging.error(f"Scheduler Job Error {m['id']}: {e}")
    
    # Poll surveys every 10 minutes (scheduler runs every minute)
    current_minute = datetime.now().minute
    if current_minute % 10 == 0:
        try:
            logging.info("Polling survey API...")
            survey_service.poll_and_sync_surveys()
            
            # Cleanup old records once daily at midnight
            if datetime.now().hour == 0:
                survey_service.cleanup_old_sync_records()
        except Exception as e:
            logging.error(f"Survey polling error: {e}")

def start_scheduler():
    """Starts the background scheduler if running on Render (Production)."""
    if os.environ.get("RENDER") == "true":
        scheduler = BackgroundScheduler()
        scheduler.add_job(func=check_pending_meetings, trigger="interval", seconds=60)
        scheduler.start()
        atexit.register(lambda: scheduler.shutdown())
        logging.info("Scheduler started.")
    else:
        logging.info("Scheduler skipped (Not in Production Mode).")
