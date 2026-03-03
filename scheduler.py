import os
import atexit
import logging
from datetime import datetime, timedelta
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


def _trigger_survey_webhook_for_meeting(meeting_row, reason=""):
    """
    Fire survey webhook for a meeting if not already sent.
    Returns True when already sent or newly sent, False on failure.
    """
    meeting_id = _row_get(meeting_row, "id")
    survey_status = (str(_row_get(meeting_row, "survey_status", "pending")) or "pending").strip().lower()

    if survey_status == "sent":
        return True

    try:
        client_id = _row_get(meeting_row, "client_id")
        client_row = db.execute_query(
            "SELECT name, email FROM clients WHERE id = ?",
            (client_id,),
            fetch_one=True
        ) if client_id else None

        client_name = _row_get(client_row, "name", "the client")
        client_email = _row_get(client_row, "email")

        target_phone = _row_get(meeting_row, "salesperson_phone")
        organizer_email = None
        if target_phone:
            normalized_target = normalize_phone(target_phone)
            user = db.execute_query(
                "SELECT email FROM users WHERE phone = ? OR phone = ? OR REPLACE(phone, 'whatsapp:', '') = REPLACE(?, 'whatsapp:', '') LIMIT 1",
                (target_phone, normalized_target, target_phone),
                fetch_one=True
            )
            organizer_email = _row_get(user, "email")

        webhook_payload = {
            "meeting_id": meeting_id,
            "aux_meeting_id": _row_get(meeting_row, "aux_meeting_id"),
            "title": _row_get(meeting_row, "title", "Sales Meeting"),
            "organizer_email": organizer_email,
            "client_email": client_email,
            "client_name": client_name,
            "status": "finished"
        }

        logging.info(
            f"[SCHEDULER] Triggering survey webhook for meeting {meeting_id}"
            f"{' (' + reason + ')' if reason else ''}"
        )
        survey_result = aux_service.trigger_survey_webhook(webhook_payload)
        if survey_result:
            db.execute_query(
                "UPDATE meetings SET survey_status = 'sent' WHERE id = ?",
                (meeting_id,),
                commit=True
            )
            logging.info(f"[SCHEDULER] Survey webhook sent for meeting {meeting_id}")
            return True

        db.execute_query(
            "UPDATE meetings SET survey_status = 'failed' WHERE id = ?",
            (meeting_id,),
            commit=True
        )
        logging.warning(f"[SCHEDULER] Survey webhook returned empty response for meeting {meeting_id}")
        return False
    except Exception as e:
        db.execute_query(
            "UPDATE meetings SET survey_status = 'failed' WHERE id = ?",
            (meeting_id,),
            commit=True
        )
        logging.error(f"[SCHEDULER] Survey webhook failed for meeting {meeting_id}: {e}")
        return False


def check_pending_meetings():
    """
    Periodic job:
    1) Send post-meeting reminder and survey once meeting end is reached.
    2) Poll Aux status + dedicated transcript API and process transcripts.
    3) Poll external survey API periodically.
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
            meeting_id = _row_get(m, "id")
            logging.info(
                f"[SCHEDULER] Processing meeting {meeting_id}: "
                f"{_row_get(m, 'title', 'Untitled')}"
            )

            if _row_get(m, "end_time"):
                end_dt = parse_iso_datetime(_row_get(m, "end_time"))
            else:
                start_dt = parse_iso_datetime(_row_get(m, "start_time"))
                end_dt = start_dt + timedelta(minutes=30)
                logging.warning(f"[SCHEDULER] Meeting {meeting_id} missing end_time, using fallback: {end_dt}")

            logging.info(f"[SCHEDULER] Meeting {meeting_id} time check: now={now_utc}, end={end_dt}")

            if now_utc >= end_dt:
                target_phone = _row_get(m, "salesperson_phone")
                current_status = (str(_row_get(m, "status", "")) or "").strip().lower()

                if not target_phone:
                    logging.warning(
                        f"[SCHEDULER] Meeting {meeting_id} has no salesperson_phone, "
                        f"marking as reminder_sent"
                    )
                    db.execute_query(
                        "UPDATE meetings SET status = 'reminder_sent' WHERE id = ?",
                        (meeting_id,),
                        commit=True
                    )
                    continue

                client_row = db.execute_query(
                    "SELECT name FROM clients WHERE id = ?",
                    (_row_get(m, "client_id"),),
                    fetch_one=True
                )
                client_name = _row_get(client_row, "name", "the client")

                # Ensure survey is triggered as soon as meeting finishes.
                _trigger_survey_webhook_for_meeting(m, reason="meeting_end_time")

                if current_status == "scheduled":
                    msg = (
                        f"Meeting with {client_name} finished. "
                        f"How did it go? (Reply 'Done' to log to HubSpot)"
                    )
                    whatsapp_service.send_whatsapp_message(target_phone, msg)
                    db.execute_query(
                        "UPDATE meetings SET status = 'reminder_sent' WHERE id = ?",
                        (meeting_id,),
                        commit=True
                    )
                    logging.info(f"[SCHEDULER] Meeting {meeting_id} marked as reminder_sent")
            else:
                logging.info(f"[SCHEDULER] Meeting {meeting_id} still in progress or upcoming")

        except Exception as e:
            logging.error(f"[SCHEDULER] ERROR processing meeting {_row_get(m, 'id')}: {e}")
            import traceback
            logging.error(f"[SCHEDULER] Traceback: {traceback.format_exc()}")

    logging.info("=" * 60)
    logging.info("[SCHEDULER] Starting AUX API transcript polling...")

    aux_meetings = db.execute_query(
        "SELECT * FROM meetings WHERE aux_meeting_token IS NOT NULL AND status IN ('scheduled', 'reminder_sent', 'pending') ORDER BY id DESC LIMIT 25",
        fetch_all=True
    ) or []
    logging.info(f"[SCHEDULER] Found {len(aux_meetings)} meetings with aux_meeting_token for polling")

    terminal_statuses = {"completed", "complete", "done", "processed", "transcribed"}

    for am in aux_meetings:
        meeting_id = _row_get(am, "id")
        token = _row_get(am, "aux_meeting_token")
        start_time_str = _row_get(am, "start_time")

        if start_time_str:
            try:
                start_dt = parse_iso_datetime(start_time_str)
                if now_utc > (start_dt + timedelta(hours=24)):
                    logging.warning(f"[SCHEDULER] Meeting {meeting_id} is >24h old. Marking failed.")
                    db.execute_query("UPDATE meetings SET status = 'failed' WHERE id = ?", (meeting_id,), commit=True)
                    continue
                if now_utc < (start_dt - timedelta(hours=1)):
                    continue
            except Exception as e:
                logging.error(f"[SCHEDULER] Error parsing start_time for meeting {meeting_id}: {e}")

        try:
            if token:
                logging.info(f"[SCHEDULER] Polling AUX status for meeting {meeting_id}, token: {token[:20]}...")
            else:
                logging.info(f"[SCHEDULER] No AUX token for meeting {meeting_id}; transcript endpoint only")

            status_data = aux_service.get_meeting_status(token) if token else {}
            status_data = status_data or {}
            if not isinstance(status_data, dict):
                status_data = {}

            api_status = status_data.get("status")
            api_status_norm = str(api_status).lower() if api_status is not None else ""
            logging.info(
                f"[SCHEDULER] Meeting {meeting_id} AUX status: {api_status}, "
                f"bot_state: {status_data.get('attendee_bot_state')}"
            )

            # New transcript API:
            # https://coachlink360.aux-rolplay.com/api/meetings/{meeting_no}/transcript
            aux_meeting_id = _row_get(am, "aux_meeting_id")
            transcript_data = aux_service.get_meeting_transcript(aux_meeting_id) if aux_meeting_id else None

            combined_payload = dict(status_data)
            if transcript_data:
                combined_payload["transcript"] = transcript_data

            transcript_preview = meeting_service.extract_aux_transcript_content(combined_payload)

            # Trigger survey quickly as soon as AUX confirms completion.
            if api_status_norm in terminal_statuses:
                _trigger_survey_webhook_for_meeting(am, reason=f"aux_status:{api_status_norm}")

            if transcript_preview:
                logging.info(f"[SCHEDULER] Meeting {meeting_id} transcript available. Processing transcript...")
                success = meeting_service.process_aux_transcript(am, combined_payload)
                if success:
                    db.execute_query("UPDATE meetings SET status = 'completed' WHERE id = ?", (meeting_id,), commit=True)
                    logging.info(f"[SCHEDULER] Meeting {meeting_id} fully processed and marked completed.")
                else:
                    logging.warning(f"[SCHEDULER] Meeting {meeting_id} transcript processing returned False")
            elif api_status_norm in terminal_statuses:
                logging.info(
                    f"[SCHEDULER] Meeting {meeting_id} is terminal ({api_status_norm}) "
                    f"but transcript is not ready yet; will retry."
                )
            else:
                logging.info(f"[SCHEDULER] Meeting {meeting_id} not yet completed (status: {api_status})")

        except Exception as e:
            logging.error(f"[SCHEDULER] ERROR polling Aux status for meeting {meeting_id}: {e}")
            import traceback
            logging.error(f"[SCHEDULER] Traceback: {traceback.format_exc()}")

    logging.info("[SCHEDULER] AUX API polling completed")
    logging.info("=" * 60)

    current_minute = datetime.now().minute
    if current_minute % 10 == 0:
        try:
            logging.info("[SCHEDULER] Polling survey API...")
            survey_service.poll_and_sync_surveys()
            if datetime.now().hour == 0:
                survey_service.cleanup_old_sync_records()
        except Exception as e:
            logging.error(f"[SCHEDULER] Survey polling error: {e}")


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
