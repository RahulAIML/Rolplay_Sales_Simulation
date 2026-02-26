import os
import atexit
import logging
from datetime import datetime, timedelta
import pytz
from apscheduler.schedulers.background import BackgroundScheduler

from database import db
from utils import parse_iso_datetime, normalize_phone
from services import whatsapp_service, aux_service, meeting_service

def _is_truthy(val):
    return str(val).strip().lower() in {"1", "true", "yes", "on"}

def _row_get(row, key, default=None):
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except Exception:
        return default

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
    logging.info("=" * 60)
    logging.info(f"[SCHEDULER] check_pending_meetings() started at {now_utc}")
    
    meetings = db.execute_query(
        "SELECT * FROM meetings WHERE status IN ('scheduled', 'reminder_sent')",
        fetch_all=True
    ) or []
    logging.info(f"[SCHEDULER] Found {len(meetings)} meetings with status in ('scheduled','reminder_sent')")
    
    for m in meetings:
        try:
            meeting_id = m['id']
            logging.info(f"[SCHEDULER] Processing meeting {meeting_id}: {_row_get(m, 'title', 'Untitled')}")
            logging.info(f"[SCHEDULER] Meeting data: outlook_id={_row_get(m, 'outlook_event_id')}, start={_row_get(m, 'start_time')}, end={_row_get(m, 'end_time')}, aux_token={_row_get(m, 'aux_meeting_token')}")
            
            # End Time Parsing
            if m['end_time']:
                end_dt = parse_iso_datetime(m['end_time'])
                logging.info(f"[SCHEDULER] Meeting {meeting_id} end_time parsed: {end_dt}")
            else:
                # Fallback if null (shouldn't happen with new logic)
                start_dt = parse_iso_datetime(m['start_time'])
                end_dt = start_dt + timedelta(minutes=30)
                logging.warning(f"[SCHEDULER] Meeting {meeting_id} has no end_time, using fallback: {end_dt}")
            
            # Logic: 1 minute buffer (Both are UTC aware)
            time_diff = now_utc - end_dt
            logging.info(f"[SCHEDULER] Meeting {meeting_id} time check: now={now_utc}, end={end_dt}, diff={time_diff}")
            
            if now_utc >= (end_dt + timedelta(minutes=1)):
                logging.info(f"[SCHEDULER] Meeting {meeting_id} has finished (past end time + 1min buffer)")
                target_phone = m['salesperson_phone']
                current_status = (str(_row_get(m, "status", "")) or "").strip().lower()
                survey_status = (str(_row_get(m, "survey_status", "pending")) or "pending").strip().lower()
                
                # Check if we should message (Registered Users Only)
                if not target_phone:
                    logging.warning(f"[SCHEDULER] Meeting {meeting_id} has no salesperson_phone, marking as reminder_sent silently")
                    # Mark processed silently so we don't loop forever
                    db.execute_query("UPDATE meetings SET status = 'reminder_sent' WHERE id = ?", (meeting_id,), commit=True)
                    continue

                # Get Client Contact Info
                crow = db.execute_query("SELECT name, email FROM clients WHERE id = ?", (m['client_id'],), fetch_one=True)
                cname = crow['name'] if crow else "the client"
                client_email = crow['email'] if crow else None
                logging.info(f"[SCHEDULER] Meeting {meeting_id} client: {cname} ({client_email})")

                # Get Salesperson Email
                normalized_target = normalize_phone(target_phone)
                user = db.execute_query(
                    "SELECT email FROM users WHERE phone = ? OR phone = ? OR REPLACE(phone, 'whatsapp:', '') = REPLACE(?, 'whatsapp:', '') LIMIT 1",
                    (target_phone, normalized_target, target_phone),
                    fetch_one=True
                )
                sp_email = user['email'] if user else None
                logging.info(f"[SCHEDULER] Meeting {meeting_id} salesperson: {sp_email}")
                
                # Trigger Survey Webhook (retryable until sent)
                if survey_status != "sent":
                    try:
                        webhook_payload = {
                            "meeting_id": meeting_id,
                            "aux_meeting_id": m['aux_meeting_id'],
                            "title": _row_get(m, 'title', 'Sales Meeting'),
                            "organizer_email": sp_email,
                            "client_email": client_email,
                            "client_name": cname,
                            "status": "finished"
                        }
                        logging.info(f"[SCHEDULER] Triggering survey webhook for meeting {meeting_id}")
                        survey_result = aux_service.trigger_survey_webhook(webhook_payload)
                        if survey_result:
                            db.execute_query(
                                "UPDATE meetings SET survey_status = 'sent' WHERE id = ?",
                                (meeting_id,),
                                commit=True
                            )
                            logging.info(f"[SCHEDULER] Survey webhook triggered for meeting {meeting_id}")
                        else:
                            db.execute_query(
                                "UPDATE meetings SET survey_status = 'failed' WHERE id = ?",
                                (meeting_id,),
                                commit=True
                            )
                            logging.warning(f"[SCHEDULER] Survey webhook trigger returned no result for meeting {meeting_id}")
                    except Exception as e:
                        db.execute_query(
                            "UPDATE meetings SET survey_status = 'failed' WHERE id = ?",
                            (meeting_id,),
                            commit=True
                        )
                        logging.error(f"[SCHEDULER] Failed to trigger survey webhook for meeting {meeting_id}: {e}")

                # Send WhatsApp reminder only once (when transitioning from scheduled)
                if current_status == "scheduled":
                    msg = f"ðŸ”” Meeting with {cname} finished. How did it go? (Reply 'Done' to log to HubSpot)"
                    logging.info(f"[SCHEDULER] Sending WhatsApp reminder to {target_phone}")
                    whatsapp_service.send_whatsapp_message(target_phone, msg)
                    
                    # Update Status
                    db.execute_query("UPDATE meetings SET status = 'reminder_sent' WHERE id = ?", (meeting_id,), commit=True)
                    logging.info(f"[SCHEDULER] Meeting {meeting_id} marked as 'reminder_sent'")
            else:
                logging.info(f"[SCHEDULER] Meeting {meeting_id} still in progress or upcoming")
                
        except Exception as e:
            logging.error(f"[SCHEDULER] ERROR processing meeting {_row_get(m, 'id')}: {e}")
            import traceback
            logging.error(f"[SCHEDULER] Traceback: {traceback.format_exc}")
    
    # 2. POLL AUX API FOR TRANSCRIPTS
    # Find meetings that have an Aux token but aren't fully processed yet.
    # Optimization: Only poll meetings that are 'active' (e.g., within 24 hours of start time)
    logging.info("=" * 60)
    logging.info("[SCHEDULER] Starting AUX API transcript polling...")
    
    # We poll meetings with a token and status 'scheduled' or 'reminder_sent'
    aux_meetings = db.execute_query(
        "SELECT * FROM meetings WHERE aux_meeting_token IS NOT NULL AND status IN ('scheduled', 'reminder_sent', 'pending') ORDER BY id DESC LIMIT 25",
        fetch_all=True
    ) or []
    
    logging.info(f"[SCHEDULER] Found {len(aux_meetings)} total meetings with aux_meeting_token ready for polling")
    
    for am in aux_meetings:
        meeting_id = am['id']
        token = am['aux_meeting_token']
        start_time_str = _row_get(am, 'start_time')
        
        # Deduplication/Efficiency: Skip polling if meeting is too old (e.g. > 24 hours) or too far in future
        if start_time_str:
            try:
                start_dt = parse_iso_datetime(start_time_str)
                # If meeting started > 24 hours ago and still not completed, mark as failed/skipped to stop polling
                if now_utc > (start_dt + timedelta(hours=24)):
                    logging.warning(f"[SCHEDULER] Meeting {meeting_id} is > 24h old and still pending. Marking as 'failed' to stop polling.")
                    db.execute_query("UPDATE meetings SET status = 'failed' WHERE id = ?", (meeting_id,), commit=True)
                    continue
                
                # If meeting is > 1 hour in the future, don't poll yet (optional optimization)
                if now_utc < (start_dt - timedelta(hours=1)):
                    # logging.info(f"[SCHEDULER] Meeting {meeting_id} is too far in the future, skipping poll.")
                    continue
            except Exception as e:
                logging.error(f"[SCHEDULER] Error parsing start_time for meeting {meeting_id}: {e}")

        try:
            logging.info(f"[SCHEDULER] Polling AUX status for meeting {meeting_id}, token: {token[:20]}...")
            
            status_data = aux_service.get_meeting_status(token)
            
            if status_data:
                api_status = status_data.get("status")
                bot_state = status_data.get("attendee_bot_state")
                logging.info(f"[SCHEDULER] Meeting {meeting_id} AUX status: {api_status}, bot_state: {bot_state}")
                
                transcript_preview = meeting_service.extract_aux_transcript_content(status_data)
                terminal_statuses = {"completed", "complete", "done", "processed", "transcribed"}
                should_process = (str(api_status).lower() in terminal_statuses) or bool(transcript_preview)

                if should_process:
                    logging.info(f"[SCHEDULER] Meeting {meeting_id} is completed. Processing transcript...")
                    success = meeting_service.process_aux_transcript(am, status_data)
                    
                    if success:
                        db.execute_query("UPDATE meetings SET status = 'completed' WHERE id = ?", (meeting_id,), commit=True)
                        logging.info(f"[SCHEDULER] Meeting {meeting_id} fully processed and marked completed.")
                    else:
                        logging.warning(f"[SCHEDULER] Meeting {meeting_id} transcript processing returned False")
                else:
                    logging.info(f"[SCHEDULER] Meeting {meeting_id} not yet completed (status: {api_status})")
            else:
                logging.warning(f"[SCHEDULER] get_meeting_status returned None for meeting {meeting_id}")
                
        except Exception as e:
            logging.error(f"[SCHEDULER] ERROR polling Aux status for meeting {meeting_id}: {e}")
            import traceback
            logging.error(f"[SCHEDULER] Traceback: {traceback.format_exc()}")

    logging.info("[SCHEDULER] AUX API polling completed")
    logging.info("=" * 60)

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
    """Starts the background scheduler unless explicitly disabled."""
    render_env = os.environ.get("RENDER")
    logging.info(f"[SCHEDULER] start_scheduler() called")
    logging.info(f"[SCHEDULER] RENDER env var: {render_env}")

    if not _is_truthy(os.getenv("ENABLE_SCHEDULER", "true")):
        logging.info("[SCHEDULER] Scheduler disabled via ENABLE_SCHEDULER")
        return

    if not _is_truthy(os.getenv("SCHEDULER_LEADER", "true")):
        logging.info("[SCHEDULER] Scheduler not started on this instance (SCHEDULER_LEADER=false)")
        return

    logging.info("[SCHEDULER] Starting BackgroundScheduler with 60s interval")
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        func=check_pending_meetings,
        trigger="interval",
        seconds=60,
        id="check_pending_meetings",
        replace_existing=True,
        max_instances=1,
        coalesce=True
    )
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown())
    logging.info("[SCHEDULER] Scheduler started successfully")
