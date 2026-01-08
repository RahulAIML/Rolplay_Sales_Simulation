import logging
import os
import time
from datetime import datetime
from database import db
from utils import normalize_phone, parse_iso_datetime
from services import ai_service, whatsapp_service, hubspot_service

# Constants
ADMIN_WHATSAPP_TO = os.getenv("ADMIN_WHATSAPP_TO")

def process_outlook_webhook(data: dict) -> dict:
    """
    Main entry point for processing webhook data from Make.com.
    Orchestrates: Parser -> DB -> AI -> WhatsApp.
    """
    logging.info(f"Processing Webhook: {data}")

    # 1. Parse & Validate
    meeting = data.get("meeting")
    
    # MANDATORY: Meeting data
    if not meeting:
        logging.error("Webhook Error: Missing 'meeting' data in payload.")
        # Return 200 to stop Make.com retries for bad payloads
        return {"status": "ignored", "message": "Missing meeting data"}, 200

    # OPTIONAL: Client data
    client = data.get("client")
    if not client:
        logging.info("No client data provided. Proceeding without CRM enrichment.")
    
    # Organizer Email (Key for User Lookup)
    organizer = meeting.get("organizer", {})
    org_email = None
    
    logging.info(f"[DEBUG] Organizer Type: {type(organizer)}")
    logging.info(f"[DEBUG] Organizer Value: {organizer}")
    logging.info(f"[DEBUG] DB Mode: {'Postgres' if db.is_postgres else 'SQLite'}")

    if isinstance(organizer, dict):
        logging.info("[DEBUG] Organizer is dict")
        raw_email = organizer.get("email") or organizer.get("address")
        # Check if it looks like a JSON string '{"name":...}'
        if isinstance(raw_email, str) and raw_email.strip().startswith('{'):
            logging.info("[DEBUG] raw_email looks like JSON")
            try:
                import json
                parsed = json.loads(raw_email)
                org_email = parsed.get("address") or parsed.get("email") or parsed.get("emailAddress", {}).get("address")
                logging.info(f"[DEBUG] Parsed email from raw_email: {org_email}")
            except Exception as e:
                logging.error(f"[DEBUG] JSON parse error (raw_email): {e}")
                org_email = raw_email
        else:
            org_email = raw_email
    elif isinstance(organizer, str):
        logging.info("[DEBUG] Organizer is string")
        clean_org = organizer.strip()
        if clean_org.startswith('{'):
            logging.info("[DEBUG] Organizer starts with {")
            try:
                import json
                parsed = json.loads(clean_org)
                org_email = parsed.get("address") or parsed.get("email") or parsed.get("emailAddress", {}).get("address")
                logging.info(f"[DEBUG] Parsed email from organizer string: {org_email}")
            except Exception as e:
                logging.error(f"[DEBUG] JSON parse error (organizer string): {e}")
                org_email = organizer
        else:
             logging.info("[DEBUG] Organizer does not start with {")
             org_email = str(organizer)
    else:
        logging.info("[DEBUG] Organizer is other type")
        # Fallback if organizer itself is a string/other
        org_email = str(organizer)

    # 2. Identify Salesperson (User)
    sp_phone = None
    if org_email:
        # Try finding exact match first
        user = db.execute_query("SELECT phone FROM users WHERE email = ?", (org_email,), fetch_one=True)
        if user:
            sp_phone = user['phone']
            logging.info(f"Identified User via Organizer ({org_email}): {sp_phone}")
        else:
            logging.warning(f"Organizer {org_email} not registered. Ignoring meeting for messaging.")
            # We return 200 to indicate success to Make.com, but we stop processing
            return {"status": "ignored", "message": "Organizer not registered"}, 200
    else:
        logging.warning("No organizer email found in meeting data.")
        return {"status": "ignored", "message": "No organizer email"}, 200

    # 3. Save Client (Only if client data exists)
    client_id = None
    c_name = "Valued Client" # Default for AI/Meeting
    
    if client:
        c_email = client.get("email")
        # Combine names for DB compatibility
        first = client.get('first_name')
        last = client.get('last_name')
        
        if first or last:
            c_name = f"{first or ''} {last or ''}".strip()
        else:
            c_name = client.get('name', 'Valued Client')

        if c_email:
            c_exist = db.execute_query("SELECT id FROM clients WHERE email = ?", (c_email,), fetch_one=True)
            
            if c_exist:
                client_id = c_exist['id']
                # Update details
                db.execute_query(
                    "UPDATE clients SET name=?, company=?, hubspot_contact_id=? WHERE email=?",
                    (c_name, client.get("company"), client.get("hubspot_contact_id"), c_email),
                    commit=True
                )
            else:
                db.execute_query(
                    "INSERT INTO clients (email, name, company, hubspot_contact_id) VALUES (?, ?, ?, ?)",
                    (c_email, c_name, client.get("company"), client.get("hubspot_contact_id")),
                    commit=True
                )
                res = db.execute_query("SELECT id FROM clients WHERE email = ?", (c_email,), fetch_one=True)
                client_id = res['id']

    # 4. Save Meeting
    mtg_id = meeting.get("meeting_id")
    # ... check exists ...
    existing_mtg = db.execute_query("SELECT id FROM meetings WHERE outlook_event_id = ?", (mtg_id,), fetch_one=True)
    if existing_mtg:
         logging.info(f"Meeting {mtg_id} already exists. Skipping processing.")
         return {"status": "success", "message": "Meeting already processed"}, 200

    start_str = meeting.get("start_time")
    end_str = meeting.get("end_time")
    
    # Parse dates
    start_dt = parse_iso_datetime(start_str) if start_str else datetime.now()
    end_dt = parse_iso_datetime(end_str) if end_str else datetime.now()
    
    db.execute_query(
        "INSERT INTO meetings (outlook_event_id, start_time, end_time, client_id, status, salesperson_phone) VALUES (?, ?, ?, ?, 'scheduled', ?)",
        (mtg_id, start_dt, end_dt, client_id, sp_phone),
        commit=True
    )
    
    # 5. Trigger AI & Notify
    # Only if we have a salesperson phone (which we checked above)
    if sp_phone:
        coaching = ai_service.generate_coaching_plan(
            meeting_title=meeting.get("title", "Meeting"),
            client_name=c_name,
            client_company=client.get("company", "Their Company") if client else "Their Company",
            start_time=start_dt.strftime("%I:%M %p")
        )

        
        # Format Message
        steps_text = "\n".join(f"- {s}" for s in coaching.get("steps", []))
        msg = (
            f"🚀 *New Meeting: {meeting.get('title')}*\n"
            f"{coaching.get('greeting')}\n\n"
            f"🎯 *Scenario*: {coaching.get('scenario')}\n\n"
            f"📋 *Prep Steps*:\n{steps_text}\n\n"
            f"💡 *Reply*: {coaching.get('recommended_reply')}"
        )
        
        whatsapp_service.send_whatsapp_message(sp_phone, msg)
        logging.info(f"Coaching sent to {sp_phone}")
    
    return {"status": "success"}

def process_read_ai_webhook(data: dict):
    """
    Processes incoming webhook from Read AI.
    Matches summary to existing meeting by start_time (+/- 10 mins).
    Updates DB and notifies Salesperson via WhatsApp.
    """
    logging.info(f"Processing Read AI Webhook: {data}")
    
    # 1. Parse Data
    # Adjust structure based on actual Read AI payload. 
    # Assuming: { "meeting": { "start_time": "...", ... }, "summary": "...", "report_url": "..." }
    meeting_data = data.get("meeting", {})
    summary_text = data.get("summary", "")
    report_url = data.get("report_url", "")
    
    if isinstance(summary_text, dict):
        summary_text = summary_text.get("text", "")

    start_str = meeting_data.get("start_time")
    
    if not start_str or not summary_text:
        logging.warning("Read AI payload missing start_time or summary. Ignoring.")
        return

    webhook_dt = parse_iso_datetime(start_str)
    
    # 2. Find Matching Meeting in DB
    # Fetch recent meetings to find a match. 
    # Since we don't have SQL time functions guaranteed across SQLite/PG easily in this helper,
    # we'll fetch candidate meetings (e.g. last 7 days) and filter in Python.
    # In production, use usage-specific SQL.
    candidates = db.execute_query(
        "SELECT * FROM meetings WHERE start_time IS NOT NULL ORDER BY id DESC LIMIT 50", 
        fetch_all=True
    ) or []
    
    matched_meeting = None
    from datetime import timedelta
    
    for m in candidates:
        try:
            m_dt = parse_iso_datetime(m['start_time'])
            # Check if within 10 minutes diff
            diff = abs(m_dt - webhook_dt)
            if diff <= timedelta(minutes=10):
                matched_meeting = m
                break
        except Exception:
            continue
            
    if not matched_meeting:
        logging.warning(f"No matching meeting found for Read AI summary @ {start_str}")
        return

    # 3. Update DB
    db.execute_query(
        "UPDATE meetings SET summary = ?, read_ai_url = ? WHERE id = ?",
        (summary_text, report_url, matched_meeting['id']),
        commit=True
    )
    logging.info(f"Attached summary to meeting {matched_meeting['id']}")

    # 4. Notify Salesperson
    target_phone = matched_meeting['salesperson_phone']
    if target_phone:
        # Get Client Name for context
        crow = db.execute_query("SELECT name FROM clients WHERE id = ?", (matched_meeting['client_id'],), fetch_one=True)
        cname = crow['name'] if crow else "Client"
        
        # Truncate summary for WhatsApp if too long
        display_summary = summary_text[:500] + "..." if len(summary_text) > 500 else summary_text
        
        msg = (
            f"📝 *Meeting Summary Ready ({cname})*\n\n"
            f"{display_summary}\n\n"
            f"🔗 Full Report: {report_url}"
        )
        whatsapp_service.send_whatsapp_message(target_phone, msg)


def handle_incoming_message(sender: str, message_body: str) -> str:
    """
    Handles incoming WhatsApp messages:
    - Matches sender to active meeting.
    - Processes commands ("Done").
    - Triggers AI Chat for everything else.
    """
    sender = normalize_phone(sender)
    
    # Find active meeting for this sender
    m = db.execute_query(
        "SELECT * FROM meetings WHERE salesperson_phone = ? AND status IN ('scheduled', 'reminder_sent') ORDER BY id DESC LIMIT 1", 
        (sender,), 
        fetch_one=True
    )
    
    if not m:
        return "No active meeting found pending feedback."

    # Log Message
    db.execute_query(
        "INSERT INTO messages (client_id, direction, message, timestamp) VALUES (?, 'incoming', ?, ?)",
        (m['client_id'], message_body, datetime.now().isoformat()), 
        commit=True
    )

    # Command: DONE
    if "done" in message_body.lower() or "completed" in message_body.lower():
        db.execute_query("UPDATE meetings SET status='completed' WHERE id=?", (m['id'],), commit=True)
        hubspot_service.sync_note_to_contact(m['client_id'], f"Feedback: {message_body}")
        
        return "✅ Meeting marked as completed notes synced to CRM."
    
    # Command: Chat (Default)
    # Get Context
    client = db.execute_query("SELECT name, company FROM clients WHERE id = ?", (m['client_id'],), fetch_one=True)
    c_name = client['name'] if client else "the client"
    
    context = f"Salesperson is meeting with {c_name} from {client['company'] if client else 'Unknown'}."
    
    reply = ai_service.generate_chat_reply(context, message_body)
    return reply

from services import transcript_service

def process_transcript_webhook(data: dict):
    """
    1. Validates & Finds Meeting in DB (via Title/Time).
    2. Fetches & Parses Transcript.
    3. Stores Transcript Lines.
    4. Generates AI Analysis.
    5. Sends WhatsApp Report.
    """
    logging.info(f"Processing Transcript Webhook: {data}")
    
    title = data.get("meeting_title")
    time_str = data.get("meeting_time")
    url = data.get("transcript_url")
    
    if not (title and time_str and url):
        raise ValueError("Missing title, time, or url")

    # 1. Find Meeting
    # Fuzzy match by time (similar to previous approach)
    webhook_dt = parse_iso_datetime(time_str)
    
    # Check last 30 days of meetings
    candidates = db.execute_query(
        "SELECT * FROM meetings WHERE start_time IS NOT NULL ORDER BY id DESC LIMIT 50", 
        fetch_all=True
    ) or []
    
    from datetime import timedelta
    matched_meeting = None
    
    for m in candidates:
        try:
            m_dt = parse_iso_datetime(m['start_time'])
            # 15 min tolerance?
            if abs(m_dt - webhook_dt) <= timedelta(minutes=20):
                matched_meeting = m
                break
        except:
            continue
            
    if not matched_meeting:
        logging.warning("No matching meeting found for transcript.")
        return {"status": "skipped", "reason": "No meeting found"}

    # 2. Fetch & Parse
    # 2. Fetch & Parse
    source = data.get("source", "read_ai")
    try:
        content = transcript_service.fetch_transcript(url)
    except Exception:
        logging.error(f"Failed to fetch transcript from {url}. Silently failing.")
        return {"status": "error", "message": "Fetch failed (silent)"}

    lines = transcript_service.parse_transcript(content)
    
    # 3. Store (Pass source)
    transcript_service.store_transcript(matched_meeting['id'], lines, source=source)
    
    # 4. Analyze
    full_text = transcript_service.get_full_transcript_text(lines)
    analysis = ai_service.generate_post_meeting_analysis(full_text)
    
    # 5. Notify
    phone = matched_meeting['salesperson_phone']
    if phone and analysis:
        # Format Report
        objections = "\n".join([f"• \"{o['quote']}\"" for o in analysis.get('objections', [])])
        next_steps = "\n".join([f"• {s}" for s in analysis.get('follow_up_actions', [])])
        
        if not objections:
            objections = "None detected."
            
        msg = (
            f"🧠 *Post-Meeting Analysis ({title})*\n\n"
            f"🛑 *Objections*:\n{objections}\n\n"
            f"📈 *Buying Signals*: {len(analysis.get('buying_signals', []))} detected\n"
            f"⚠️ *Risks*: {len(analysis.get('risks', []))} identified\n\n"
            f"🚀 *Next Steps*:\n{next_steps}\n\n"
            f"👉 Reply *Done* after you have followed up."
        )
        whatsapp_service.send_whatsapp_message(phone, msg)
        
    return {"status": "processed", "meeting_id": matched_meeting['id']}

