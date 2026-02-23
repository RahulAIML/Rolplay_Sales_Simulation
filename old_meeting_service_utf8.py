import logging
import os
from datetime import datetime, timedelta
from database import db
from utils import normalize_phone, parse_iso_datetime, to_local_time, get_current_utc_time
from services import ai_service, whatsapp_service, hubspot_service, transcript_service, aux_service

# Constants
ADMIN_WHATSAPP_TO = os.getenv("ADMIN_WHATSAPP_TO")

def process_outlook_webhook(data: dict) -> dict:
    """
    Main entry point for processing webhook data from Make.com.
    Orchestrates: Parser -> DB -> AI -> WhatsApp -> Background Sync (Aux/HubSpot).
    """
    logging.info(f"Processing Webhook: {data}")

    # 1. Parse & Validate
    meeting = data.get("meeting") or data.get("Meeting Payload")
    if meeting:
        normalized = {}
        for k, v in meeting.items():
            normalized[k.lower().replace(" ", "_")] = v
        meeting = normalized

    if not meeting:
        logging.error(f"Webhook Error: Missing 'meeting' data in payload.")
        return {"status": "ignored", "message": "Missing meeting data"}, 200

    client_data = data.get("client") or data.get("Client")
    if client_data:
        curr_client = {}
        for k, v in client_data.items():
            curr_client[k.lower().replace(" ", "_")] = v
        client_data = curr_client

    # Organizer Email (Key for User Lookup)
    organizer = meeting.get("organizer", {})
    org_email = None
    if isinstance(organizer, dict):
        org_email = organizer.get("email") or organizer.get("address")
    else:
        org_email = str(organizer)

    # 2. Identify Salesperson (User)
    user = db.execute_query("SELECT phone, timezone FROM users WHERE email = ?", (org_email,), fetch_one=True)
    if not user:
        logging.warning(f"Organizer {org_email} not registered. Ignoring.")
        return {"status": "ignored", "message": "Organizer not registered"}, 200

    sp_phone = user['phone']
    sp_timezone = user['timezone']

    # 3. Save/Update Client
    client_id = None
    c_name = "Valued Client"
    c_email = client_data.get("email") if client_data else None

    if client_data and c_email:
        # Combine names
        first = client_data.get('first_name')
        last = client_data.get('last_name')
        if first or last:
            c_name = f"{first or ''} {last or ''}".strip()
        else:
            c_name = client_data.get('name', 'Valued Client')

        # DB Logic
        c_exist = db.execute_query("SELECT id, hubspot_contact_id FROM clients WHERE email = ?", (c_email,), fetch_one=True)
        if c_exist:
            client_id = c_exist['id']
            db.execute_query("UPDATE clients SET name=?, company=? WHERE email=?", (c_name, client_data.get("company"), c_email), commit=True)
        else:
            db.execute_query("INSERT INTO clients (email, name, company) VALUES (?, ?, ?)", (c_email, c_name, client_data.get("company")), commit=True)
            res = db.execute_query("SELECT id FROM clients WHERE email = ?", (c_email,), fetch_one=True)
            client_id = res['id']

    # 4. HubSpot Enrichment (PRIORITY)
    hs_contact_id = None
    hs_context_str = ""
    if client_id and c_email:
        try:
            hubspot_service = __import__('services.hubspot_service', fromlist=['create_or_find_contact', 'get_contact_details'])
            hs_contact_id = hubspot_service.create_or_find_contact(c_email, c_name, client_data.get("phone", ""))
            if hs_contact_id:
                db.execute_query("UPDATE clients SET hubspot_contact_id = ? WHERE id = ?", (hs_contact_id, client_id), commit=True)
                # Fetch deeper details for AI
                hs_details = hubspot_service.get_contact_details(hs_contact_id)
                if hs_details:
                    hs_context_str = "\n\n[HubSpot context]\n"
                    for k in ['jobtitle', 'company', 'industry', 'lifecyclestage', 'notes_last_updated']:
                        if hs_details.get(k): hs_context_str += f"{k.capitalize()}: {hs_details.get(k)}\n"
        except Exception as e:
            logging.error(f"HubSpot Enrichment Error: {e}")

    # 5. Prepare Coaching Plan
    start_str = meeting.get("start_time")
    end_str = meeting.get("end_time")
    start_dt = parse_iso_datetime(start_str) if start_str else get_current_utc_time()
    end_dt = parse_iso_datetime(end_str) if end_str else (start_dt + timedelta(minutes=30))

    # Parse Body
    body_obj = meeting.get("body")
    meeting_body = ""
    if isinstance(body_obj, dict):
        meeting_body = body_obj.get("content") or body_obj.get("Content") or ""
    else:
        meeting_body = str(body_obj or "")
    
    # Enrichment
    meeting_body += hs_context_str

    loc_obj = meeting.get("location")
    location_str = loc_obj.get("display_name") if isinstance(loc_obj, dict) else str(loc_obj or "Unknown")

    # Display Time
    _local_start = to_local_time(start_dt, tz_str=sp_timezone)
    _local_end   = to_local_time(end_dt,   tz_str=sp_timezone)
    display_time = f"{_local_start.strftime('%b %d, %I:%M %p')} - {_local_end.strftime('%I:%M %p')} {_local_start.strftime('%Z')}"

    coaching = ai_service.generate_coaching_plan(
        meeting_title=meeting.get("title") or meeting.get("subject") or "Meeting",
        client_name=c_name,
        client_company=client_data.get("company", "Their Company") if client_data else "Their Company",
        start_time=display_time,
        meeting_body=meeting_body,
        location=location_str
    )

    # 6. SEND COACHING IMMEDIATELY
    msg_body = (
        f"≡ƒÜÇ *New Meeting: {meeting.get('title') or 'Upcoming Meeting'}*\n"
        f"{coaching.get('greeting')}\n\n"
        f"≡ƒÄ» *Scenario*: {coaching.get('scenario')}\n\n"
        f"≡ƒôï *Prep Steps*:\n" + "\n".join(f"- {s}" for s in coaching.get("steps", [])) + "\n\n"
        f"≡ƒÆí *Reply*: {coaching.get('recommended_reply')}"
    )
    
    # Try Template first, falls back to freeform in whatsapp_service.py if SID missing
    template_vars = {
        "1": f"≡ƒÜÇ *{meeting.get('title', 'Meeting')}*",
        "2": f"{coaching.get('greeting')}\n\n≡ƒÄ» {coaching.get('scenario')}",
        "3": f"≡ƒôï *Steps*:\n" + "\n".join(f"- {s}" for s in coaching.get("steps", []))[:200], # Twilio var limit
        "4": f"≡ƒÆí {coaching.get('recommended_reply')}"
    }
    
    whatsapp_service.send_whatsapp_message(sp_phone, body=msg_body, use_template=True, template_vars=template_vars)
    logging.info(f"Coaching sent immediately to {sp_phone}")

    # 7. Background / Slower Tasks (Safe to run after coaching)
    # 7.1. Save Meeting
    mtg_id = meeting.get("meeting_id")
    mtg_title = meeting.get("title") or meeting.get("subject") or "Sales Meeting"
    
    # Check Attendees
    atts = meeting.get("attendees", [])
    atts_str = ", ".join([str(a) for a in atts]) if isinstance(atts, list) else str(atts)

    existing_mtg = db.execute_query("SELECT id FROM meetings WHERE outlook_event_id = ?", (mtg_id,), fetch_one=True)
    if not existing_mtg:
        db.execute_query(
            "INSERT INTO meetings (outlook_event_id, start_time, end_time, client_id, status, salesperson_phone, location, attendees, summary, title) VALUES (?, ?, ?, ?, 'scheduled', ?, ?, ?, ?, ?)",
            (mtg_id, start_dt, end_dt, client_id, sp_phone, location_str, atts_str, meeting_body, mtg_title),
            commit=True
        )
    
    # 7.2. Sync Meeting Summary to HubSpot
    try:
        hubspot_service = __import__('services.hubspot_service', fromlist=['sync_meeting_summary'])
        hubspot_service.sync_meeting_summary(client_db_id=client_id, meeting_title=mtg_title, start_time=start_str, summary=meeting_body, location=location_str)
    except Exception as e:
        logging.error(f"HubSpot Sync Summary Error: {e}")

    # 7.3. Aux API Scheduling
    meeting_link = meeting.get("online_meeting_url")
    if not meeting_link:
        # Search in body
        import re
        link_pattern = r"(https?://(?:[a-zA-Z0-9-]+\.)?(?:zoom\.us|meet\.google\.com|teams\.(?:live|microsoft)\.com|teams\.microsoft\.com/l/meetup-join)/[^\s\"<>]+)"
        match = re.search(link_pattern, f"{location_str} {meeting_body}")
        if match: meeting_link = match.group(1)

    if meeting_link:
        try:
            import pytz
            start_dt_utc = start_dt.astimezone(pytz.utc) if start_dt.tzinfo else pytz.utc.localize(start_dt)
            aux_res = aux_service.schedule_meeting(meeting_link, start_dt_utc.strftime("%Y-%m-%dT%H:%M:%S+00:00"), mtg_title)
            if aux_res:
                db.execute_query("UPDATE meetings SET aux_meeting_id=?, aux_meeting_token=? WHERE outlook_event_id=?", 
                               (aux_res.get("meetingId"), aux_res.get("token"), mtg_id), commit=True)
        except Exception as e:
            logging.error(f"Aux Schedule Error: {e}")

    return {"status": "success"}

def process_read_ai_webhook(data: dict):
    """Processes incoming webhook from Read AI."""
    logging.info(f"Processing Read AI Webhook: {data}")
    meeting_data = data.get("meeting", {})
    summary_text = data.get("summary", "")
    if isinstance(summary_text, dict): summary_text = summary_text.get("text", "")
    report_url = data.get("report_url", "")
    start_str = meeting_data.get("start_time")
    
    if not start_str or not summary_text: return
    webhook_dt = parse_iso_datetime(start_str)
    
    # Match
    candidates = db.execute_query("SELECT * FROM meetings WHERE start_time IS NOT NULL ORDER BY id DESC LIMIT 50", fetch_all=True) or []
    for m in candidates:
        try:
            m_dt = parse_iso_datetime(m['start_time'])
            if abs(m_dt - webhook_dt) <= timedelta(minutes=10):
                db.execute_query("UPDATE meetings SET summary = ?, read_ai_url = ? WHERE id = ?", (summary_text, report_url, m['id']), commit=True)
                # Notify
                user = db.execute_query("SELECT name FROM clients WHERE id = ?", (m['client_id'],), fetch_one=True)
                cname = user['name'] if user else "Client"
                msg = f"≡ƒô¥ *Meeting Summary Ready ({cname})*\n\n{summary_text[:500]}...\n\n≡ƒöù {report_url}"
                whatsapp_service.send_whatsapp_message(m['salesperson_phone'], msg)
                break
        except Exception: continue


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
        
        return "Γ£à Meeting marked as completed notes synced to CRM."
    
    # Command: Chat (Default)
    # Get Context
    client = db.execute_query("SELECT name, company FROM clients WHERE id = ?", (m['client_id'],), fetch_one=True)
    c_name = client['name'] if client else "the client"
    
    # Try to fetch transcript/summary from meets
    summary_context = m.get('summary', '')

    context = f"Salesperson is meeting with {c_name} from {client['company'] if client else 'Unknown'}."
    
    start = m.get('start_time')
    end = m.get('end_time')
    loc = m.get('location') or 'Unknown'
    atts = m.get('attendees') or 'Unknown'
    
    # Look up salesperson's timezone for correct local time display
    sp_tz = None
    try:
        sp_user = db.execute_query("SELECT timezone FROM users WHERE phone = ?", (sender,), fetch_one=True)
        if sp_user:
            sp_tz = sp_user['timezone'] or None
    except Exception:
        pass

    # Try to parse ISO times to readable (Localize for Organizer's timezone)
    try:
        s_dt = parse_iso_datetime(start) if start else None
        e_dt = parse_iso_datetime(end) if end else None
        if s_dt and e_dt:
            # Use per-user timezone ΓÇö falls back to APP_TIMEZONE then UTC
            s_local = to_local_time(s_dt, tz_str=sp_tz)
            e_local = to_local_time(e_dt, tz_str=sp_tz)
            tz_abbr = s_local.strftime("%Z")
            time_str = f"{s_local.strftime('%b %d, %I:%M %p')} - {e_local.strftime('%I:%M %p')} {tz_abbr}"
        else:
            time_str = "Unknown Time"
    except:
        time_str = "Unknown Time"
        
    context += f"\nTime: {time_str}\nLocation: {loc}\nAttendees: {atts}"
    
    # 5. Fetch Full Transcript (NEW)
    # Check if transcripts exist for this meeting
    t_rows = db.execute_query(
        "SELECT speaker, text FROM meeting_transcripts WHERE meeting_id = ? ORDER BY id ASC", 
        (m['id'],), 
        fetch_all=True
    )
    
    transcript_text = ""
    if t_rows:
        # Reconstruct transcript
        # Limit to last ~300 lines to fit context window (approx 6-8k tokens)
        MAX_LINES = 300
        if len(t_rows) > MAX_LINES:
            transcript_text += "...[Truncated Preview]...\n"
            t_rows = t_rows[-MAX_LINES:]
            
        transcript_text = "\n".join([f"{r['speaker']}: {r['text']}" for r in t_rows])

    if transcript_text:
        context += f"\n\n[FULL TRANSCRIPT AVAILABLE]\n{transcript_text}"
    elif summary_context:
        context += f"\n\nMeeting Summary/Agenda: {summary_context[:2000]}"
    
    reply = ai_service.generate_chat_reply(context, message_body)
    return reply



def process_transcript_webhook(data: dict):
    """
    Webhook entry point for Read.ai transcripts.
    """
    logging.info(f"Processing Transcript Webhook: {data}")
    
    title = data.get("meeting_title")
    time_str = data.get("meeting_time")
    url = data.get("transcript_url")
    
    if not (title and time_str and url):
        raise ValueError("Missing title, time, or url")

    # 1. Find Meeting
    webhook_dt = parse_iso_datetime(time_str)
    candidates = db.execute_query(
        "SELECT * FROM meetings WHERE start_time IS NOT NULL ORDER BY id DESC LIMIT 50", 
        fetch_all=True
    ) or []
    
    matched_meeting = None
    for m in candidates:
        try:
            m_dt = parse_iso_datetime(m['start_time'])
            if abs(m_dt - webhook_dt) <= timedelta(minutes=20):
                matched_meeting = m
                break
        except:
            continue
            
    if not matched_meeting:
        logging.warning("No matching meeting found for transcript.")
        return {"status": "skipped", "reason": "No meeting found"}

    # 2. Fetch Content
    source = data.get("source", "read_ai")
    try:
        content = transcript_service.fetch_transcript(url)
    except Exception:
        logging.error(f"Failed to fetch transcript from {url}.")
        return {"status": "error", "message": "Fetch failed"}

    # 3. Process
    return process_transcript_data(matched_meeting, content, title, source, url)

def process_aux_transcript(meeting_row, aux_data):
    """
    Processes transcript data specifically from the Aux API response.
    """
    transcript_info = aux_data.get("transcript", {})
    content = transcript_info.get("content", "")
    title = aux_data.get("title", "Aux Meeting")
    
    if not content:
        logging.warning(f"No transcript content for Aux meeting {meeting_row['id']}")
        return False
        
    res = process_transcript_data(meeting_row, content, title, source="aux_api")
    return res.get("status") == "processed"

def process_transcript_data(meeting_row, transcript_content, title, source, transcript_url=None):
    """
    Core logic to parse, store, analyze and notify regarding a transcript.
    """
    meeting_id = meeting_row['id']
    
    # 1. Parse
    lines = transcript_service.parse_transcript(transcript_content)
    
    # 2. Store
    transcript_service.store_transcript(meeting_id, lines, source=source)
    
    # 3. Analyze
    full_text = transcript_service.get_full_transcript_text(lines)
    analysis = ai_service.generate_post_meeting_analysis(full_text)
    
    # 4. Notify
    phone = meeting_row['salesperson_phone']
    if phone and analysis:
        # Format Report
        objections = "\n".join([f"ΓÇó \"{o['quote']}\"" for o in analysis.get('objections', [])]) or "None detected."
        next_steps = "\n".join([f"ΓÇó {s}" for s in analysis.get('follow_up_actions', [])])
        
        template_vars = {
            "1": f"≡ƒºá *Post-Meeting Analysis ({title})*",
            "2": f"≡ƒ¢æ *Objections*:\n{objections}\n\n≡ƒôê *Buying Signals*: {len(analysis.get('buying_signals', []))} detected",
            "3": f"ΓÜá∩╕Å *Risks*: {len(analysis.get('risks', []))} identified\n\n≡ƒÜÇ *Next Steps*:\n{next_steps}",
            "4": "≡ƒæë Reply *Done* after you have followed up."
        }
        
        msg_body = (
            f"≡ƒºá *Post-Meeting Analysis ({title})*\n\n"
            f"≡ƒ¢æ *Objections*:\n{objections}\n\n"
            f"≡ƒôê *Buying Signals*: {len(analysis.get('buying_signals', []))} detected\n"
            f"ΓÜá∩╕Å *Risks*: {len(analysis.get('risks', []))} identified\n\n"
            f"≡ƒÜÇ *Next Steps*:\n{next_steps}\n\n"
            f"≡ƒæë Reply *Done* after you have followed up."
        )
        
        whatsapp_service.send_whatsapp_message(
            phone,
            body=msg_body,
            use_template=True,
            template_vars=template_vars
        )

    # 5. Log to HubSpot
    try:
        hubspot_service = __import__('services.hubspot_service', fromlist=['sync_meeting_analysis'])
        hubspot_service.sync_meeting_analysis(
            client_db_id=meeting_row['client_id'],
            meeting_title=title,
            analysis=analysis,
            transcript_url=transcript_url or "Stored in Database"
        )
    except Exception as e:
        logging.error(f"HubSpot Analysis Sync Failed: {e}")
        
    return {"status": "processed", "meeting_id": meeting_id}
