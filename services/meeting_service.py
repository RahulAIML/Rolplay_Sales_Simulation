import logging
import os
from datetime import datetime, timedelta
from database import db
from utils import normalize_phone, parse_iso_datetime
from services import ai_service, whatsapp_service, hubspot_service, transcript_service

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
    
    # Fallback for Make.com "Meeting Payload" structure
    if not meeting:
        meeting = data.get("Meeting Payload")

    # Normalize keys if meeting found (Handle "Start time" -> "start_time", "Title" -> "title")
    if meeting:
        # Create a normalized copy of the dictionary
        normalized = {}
        for k, v in meeting.items():
            # Convert "Start time" -> "start_time", "Title" -> "title"
            new_key = k.lower().replace(" ", "_")
            normalized[new_key] = v
        meeting = normalized

    # MANDATORY: Meeting data
    if not meeting:
        logging.error(f"Webhook Error: Missing 'meeting' data in payload. Received keys: {list(data.keys())}")
        # Return 200 to stop Make.com retries for bad payloads
        return {"status": "ignored", "message": "Missing meeting data"}, 200

    # OPTIONAL: Client data
    client = data.get("client")
    if not client:
        client = data.get("Client")
    
    if client:
        # Normalize client keys (e.g. "Email" -> "email", "First name" -> "first_name")
        curr_client = {}
        for k, v in client.items():
            curr_client[k.lower().replace(" ", "_")] = v
        client = curr_client

    if not client:
        logging.info("No client data provided. Proceeding without CRM enrichment.")
    
    # Organizer Email (Key for User Lookup)
    organizer = meeting.get("organizer", {})
    org_email = None

    if isinstance(organizer, dict):
        # Direct key check
        raw_email = organizer.get("email") or organizer.get("address")
        
        # Check for nested Outlook/Make structure: Organizer > Email Address > Address
        if not raw_email:
             email_obj = organizer.get("Email Address") or organizer.get("emailAddress")
             if isinstance(email_obj, dict):
                 raw_email = email_obj.get("Address") or email_obj.get("address")
        # Check if it looks like a JSON string '{"name":...}'
        if isinstance(raw_email, str) and raw_email.strip().startswith('{'):
            try:
                import json
                parsed = json.loads(raw_email)
                org_email = parsed.get("address") or parsed.get("email") or parsed.get("emailAddress", {}).get("address")
            except Exception as e:
                logging.error(f"JSON parse error (raw_email): {e}")
                org_email = raw_email
        else:
            org_email = raw_email
    elif isinstance(organizer, str):
        clean_org = organizer.strip()
        if clean_org.startswith('{'):
            try:
                import json
                parsed = json.loads(clean_org)
                org_email = parsed.get("address") or parsed.get("email") or parsed.get("emailAddress", {}).get("address")
            except Exception as e:
                logging.error(f"JSON parse error (organizer string): {e}")
                org_email = organizer
        else:
             org_email = str(organizer)
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

    # 3.5. Sync Client to HubSpot (NEW)
    hs_contact_id = None
    if client_id and c_email:
        try:
            hubspot_service = __import__('services.hubspot_service', fromlist=['create_or_find_contact'])
            # Pass empty phone if not in client data
            hs_contact_id = hubspot_service.create_or_find_contact(c_email, c_name, client.get("phone", ""))
            
            if hs_contact_id:
                db.execute_query("UPDATE clients SET hubspot_contact_id = ? WHERE id = ?", (hs_contact_id, client_id), commit=True)
                logging.info(f"HubSpot Client Synced: {c_email} -> {hs_contact_id}")
        except Exception as e:
             logging.error(f"HubSpot Client Sync Failed: {e}")

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
        # Extract Body/Agenda
        # meeting dict is already normalized locally, but original payload might be mixed.
        # However, our process_outlook_webhook normalizes keys at the top.
        # But wait, nested keys like Location.DisplayName are NOT normalized by the top loop.
        # We need to access the Meeting object again or just be careful.
        
        # We already have 'meeting' which is the normalized version of the specific sub-object.
        # Let's try to get body from it. 
        # Note: If input was "Meeting Payload": {"Body": {"Content": "..."}}, the normalized version
        # has keys like "body". If "body" was a dict {"content":...}, it stays a dict.
        
        body_obj = meeting.get("body")
        meeting_body = ""
        if isinstance(body_obj, dict):
            meeting_body = body_obj.get("content") or body_obj.get("Content") or ""
        elif isinstance(body_obj, str):
            meeting_body = body_obj
            # Check if it's a JSON string (as seen in production logs)
            if meeting_body.strip().startswith('{'):
                try:
                    import json
                    parsed_body = json.loads(meeting_body)
                    if isinstance(parsed_body, dict):
                        # Extract content from parsed JSON
                        meeting_body = parsed_body.get("content") or parsed_body.get("Content") or meeting_body
                except Exception as e:
                    logging.warning(f"Failed to parse body as JSON: {e}")
            
        # Extract Location
        loc_obj = meeting.get("location")
        location_str = "Unknown"
        if isinstance(loc_obj, dict):
            # Try various keys since sub-dicts aren't recursively normalized in line 31
            location_str = loc_obj.get("display_name") or loc_obj.get("displayName") or loc_obj.get("DisplayName") or "Unknown"
        elif isinstance(loc_obj, str):
            location_str = loc_obj

        coaching = ai_service.generate_coaching_plan(
            meeting_title=meeting.get("title", "Meeting"),
            client_name=c_name,
            client_company=client.get("company", "Their Company") if client else "Their Company",
            start_time=start_dt.strftime("%I:%M %p"),
            meeting_body=meeting_body,
            location=location_str
        )

        
        # Format Message for Template (Business-Initiated)
        steps_text = "\n".join(f"- {s}" for s in coaching.get("steps", []))
        
        # Template variables (4-variable universal template)
        template_vars = {
            "1": f"🚀 *New Meeting: {meeting.get('title')}*",
            "2": f"{coaching.get('greeting')}\n\n🎯 *Scenario*: {coaching.get('scenario')}",
            "3": f"📋 *Prep Steps*:\n{steps_text}",
            "4": f"💡 *Reply*: {coaching.get('recommended_reply')}"
        }
        
        # Plain text fallback (for when template not available)
        msg_body = (
            f"🚀 *New Meeting: {meeting.get('title')}*\n"
            f"{coaching.get('greeting')}\n\n"
            f"🎯 *Scenario*: {coaching.get('scenario')}\n\n"
            f"📋 *Prep Steps*:\n{steps_text}\n\n"
            f"💡 *Reply*: {coaching.get('recommended_reply')}"
        )
        
        whatsapp_service.send_whatsapp_message(
            sp_phone, 
            body=msg_body,
            use_template=True, 
            template_vars=template_vars
        )
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
    
    # Try to fetch transcript/summary from meets
    summary_context = m.get('summary', '')

    context = f"Salesperson is meeting with {c_name} from {client['company'] if client else 'Unknown'}."
    if summary_context:
        context += f"\n\nMeeting Summary: {summary_context[:2000]}"
    
    reply = ai_service.generate_chat_reply(context, message_body)
    return reply



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
        # Format Report for Template (Business-Initiated)
        objections = "\n".join([f"• \"{o['quote']}\"" for o in analysis.get('objections', [])])
        next_steps = "\n".join([f"• {s}" for s in analysis.get('follow_up_actions', [])])
        
        if not objections:
            objections = "None detected."
        
        # Template variables (4-variable universal template)
        template_vars = {
            "1": f"🧠 *Post-Meeting Analysis ({title})*",
            "2": f"🛑 *Objections*:\n{objections}\n\n📈 *Buying Signals*: {len(analysis.get('buying_signals', []))} detected",
            "3": f"⚠️ *Risks*: {len(analysis.get('risks', []))} identified\n\n🚀 *Next Steps*:\n{next_steps}",
            "4": "👉 Reply *Done* after you have followed up."
        }
        
        # Plain text fallback
        msg_body = (
            f"🧠 *Post-Meeting Analysis ({title})*\n\n"
            f"🛑 *Objections*:\n{objections}\n\n"
            f"📈 *Buying Signals*: {len(analysis.get('buying_signals', []))} detected\n"
            f"⚠️ *Risks*: {len(analysis.get('risks', []))} identified\n\n"
            f"🚀 *Next Steps*:\n{next_steps}\n\n"
            f"👉 Reply *Done* after you have followed up."
        )
        
        
        whatsapp_service.send_whatsapp_message(
            phone,
            body=msg_body,
            use_template=True,
            template_vars=template_vars
        )

    # 6. Log to HubSpot (NEW)
    if matched_meeting and analysis:
        try:
            hubspot_service = __import__('services.hubspot_service', fromlist=['sync_meeting_analysis'])
            hubspot_service.sync_meeting_analysis(
                client_db_id=matched_meeting['client_id'],
                meeting_title=title,
                analysis=analysis,
                transcript_url=url
            )
        except Exception as e:
            logging.error(f"HubSpot Analysis Sync Failed: {e}")
        
    return {"status": "processed", "meeting_id": matched_meeting['id']}

