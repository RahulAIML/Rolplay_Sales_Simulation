import os
import atexit
import logging
from datetime import datetime, timedelta
import pytz
from apscheduler.schedulers.background import BackgroundScheduler

from database import db
from utils import parse_iso_datetime
from services import whatsapp_service, aux_service, meeting_service

def check_pending_meetings():
    """
    Periodic job to check for finished meetings that need reminders
    and poll for new survey responses.
    Rules:
    - Status is 'scheduled'.
    - Now > EndTime + 1 minute.
    """
    from services import survey_service
    from utils import get_current_utc_time
    
    now_utc = get_current_utc_time()
    
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
            
            # Logic: 1 minute buffer (Both are UTC aware)
            if now_utc >= (end_dt + timedelta(minutes=1)):
                target_phone = m['salesperson_phone']
                
                # Check if we should message (Registered Users Only)
                if not target_phone:
                    # Mark processed silently so we don't loop forever
                    db.execute_query("UPDATE meetings SET status = 'reminder_sent' WHERE id = ?", (m['id'],), commit=True)
                    continue

                # Get Client Contact Info
                crow = db.execute_query("SELECT name, email FROM clients WHERE id = ?", (m['client_id'],), fetch_one=True)
                cname = crow['name'] if crow else "the client"
                client_email = crow['email'] if crow else None

                # Get Salesperson Email
                user = db.execute_query("SELECT email FROM users WHERE phone = ?", (target_phone,), fetch_one=True)
                sp_email = user['email'] if user else None
                
                # Trigger Survey Webhook (Replaces Read.ai email flow)
                try:
                    webhook_payload = {
                        "meeting_id": m['id'],
                        "aux_meeting_id": m['aux_meeting_id'],
                        "title": m.get('title', 'Sales Meeting'),
                        "organizer_email": sp_email,
                        "client_email": client_email,
                        "client_name": cname,
                        "status": "finished"
                    }
                    aux_service.trigger_survey_webhook(webhook_payload)
                    logging.info(f"Survey webhook triggered for meeting {m['id']}")
                except Exception as e:
                    logging.error(f"Failed to trigger survey webhook: {e}")

                # Send WhatsApp Reminder
                msg = f"🔔 Meeting with {cname} finished. How did it go? (Reply 'Done' to log to HubSpot)"
                whatsapp_service.send_whatsapp_message(target_phone, msg)
                
                # Update Status
                db.execute_query("UPDATE meetings SET status = 'reminder_sent' WHERE id = ?", (m['id'],), commit=True)
                logging.info(f"Reminder sent and webhook triggered for meeting {m['id']}")
                
        except Exception as e:
            logging.error(f"Scheduler Job Error {m['id']}: {e}")
    
    # 2. POLL AUX API FOR TRANSCRIPTS
    # Find meetings that have an Aux token but aren't fully processed yet.
    # We'll check 'reminder_sent' meetings that have an aux_token.
    aux_meetings = db.execute_query(
        "SELECT * FROM meetings WHERE aux_meeting_token IS NOT NULL AND status IN ('scheduled', 'reminder_sent')", 
        fetch_all=True
    ) or []
    
    for am in aux_meetings:
        try:
            status_data = aux_service.get_meeting_status(am['aux_meeting_token'])
            if status_data and status_data.get("status") == "completed":
                logging.info(f"Aux meeting {am['id']} is completed. Processing transcript...")
                success = meeting_service.process_aux_transcript(am, status_data)
                if success:
                    db.execute_query("UPDATE meetings SET status = 'completed' WHERE id = ?", (am['id'],), commit=True)
                    logging.info(f"Aux meeting {am['id']} fully processed and marked completed.")
        except Exception as e:
            logging.error(f"Error polling Aux status for meeting {am['id']}: {e}")

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
