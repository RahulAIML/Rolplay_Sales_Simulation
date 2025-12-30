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
    meeting = data.get("meeting", {})
    client = data.get("client", {})
    
    # Organizer Email (Key for User Lookup)
    # New structure: organizer is a dict with {name, email}
    organizer = meeting.get("organizer", {})
    if isinstance(organizer, dict):
        org_email = organizer.get("email") or organizer.get("address")
    else:
        org_email = None

    # 2. Identify Salesperson (User)
    sp_phone = None
    if org_email:
        user = db.execute_query("SELECT phone FROM users WHERE email = ?", (org_email,), fetch_one=True)
        if user:
            sp_phone = user['phone']
            logging.info(f"Identified User via Organizer ({org_email}): {sp_phone}")
        else:
            logging.warning(f"Organizer {org_email} not registered. Ignoring meeting for messaging.")

    # 3. Save Client
    # Client ID logic
    c_email = client.get("email")
    
    # Combine names for DB compatibility
    first = client.get('first_name')
    last = client.get('last_name')
    
    if first or last:
        c_name = f"{first or ''} {last or ''}".strip()
    else:
        # Fallback to legacy 'name' field
        c_name = client.get('name', 'Valued Client')
    
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
        # Fetch back
        res = db.execute_query("SELECT id FROM clients WHERE email = ?", (c_email,), fetch_one=True)
        client_id = res['id']

    # 4. Save Meeting (Idempotency Check)
    sys_id = meeting.get("meeting_id", f"sys_{int(time.time())}")
    
    existing_mtg = db.execute_query("SELECT id FROM meetings WHERE outlook_event_id = ?", (sys_id,), fetch_one=True)
    if existing_mtg:
        logging.info(f"Meeting {sys_id} already exists. Skipping processing.")
        return {"status": "skipped", "reason": "duplicate"}

    # Time Parsing
    start_dt = parse_iso_datetime(meeting.get("start_time"))
    end_dt = parse_iso_datetime(meeting.get("end_time"))
    
    # Insert
    db.execute_query(
        "INSERT INTO meetings (client_id, outlook_event_id, start_time, end_time, status, salesperson_phone) VALUES (?, ?, ?, ?, 'scheduled', ?)",
        (client_id, sys_id, start_dt.isoformat(), end_dt.isoformat(), sp_phone),
        commit=True
    )
    
    # 5. Trigger AI & Notify (Only if registered user found)
    if sp_phone:
        coaching = ai_service.generate_coaching_plan(
            meeting_title=meeting.get("title", "Meeting"),
            client_name=c_name,
            client_company=client.get("company", "Their Company"),
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
