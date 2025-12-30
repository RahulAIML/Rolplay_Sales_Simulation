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
    # New structure: organizer might be dict OR stringified JSON
    organizer = meeting.get("organizer", {})
    org_email = None

    if isinstance(organizer, dict):
        raw_email = organizer.get("email") or organizer.get("address")
        # Check if it looks like a JSON string '{"name":...}'
        if isinstance(raw_email, str) and raw_email.strip().startswith('{'):
            try:
                import json
                parsed = json.loads(raw_email)
                org_email = parsed.get("address") or parsed.get("email")
            except Exception:
                org_email = raw_email
        else:
            org_email = raw_email
    else:
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
