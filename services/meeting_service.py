import logging
import os
from datetime import datetime, timedelta
from database import db
from utils import normalize_phone, parse_iso_datetime, to_local_time, get_current_utc_time
from services import ai_service, whatsapp_service, hubspot_service, transcript_service, aux_service

# Constants
ADMIN_WHATSAPP_TO = os.getenv("ADMIN_WHATSAPP_TO")

def _get_val(d: dict, keys: list, default=None):
    """Aux helper to get value from dictionary by trying multiple key variations."""
    if not (d and isinstance(d, dict)): return default
    
    # Priority 1: Exact match
    for k in keys:
        if k in d: return d[k]
        
    # Priority 2: Normalized match (handles camelCase, spaces, etc.)
    # We strip underscores and spaces and go lowercase
    def normalize(s):
        return s.lower().replace("_", "").replace("-", "").replace(" ", "")

    normalized_keys = [normalize(k) for k in keys]
    for dk, dv in d.items():
        if normalize(dk) in normalized_keys:
            return dv
            
    return default

def _extract_meeting_link(text: str) -> str:
    """Detects meeting platform link, unwrapping safelinks if needed."""
    if not text: return None
    import re
    import urllib.parse

    # 1. Any URL pattern
    url_pattern = r"(https?://[^\s\"<>]+)"
    urls = re.findall(url_pattern, text)
    
    platforms = ['zoom.us', 'zoom.com', 'meet.google.com', 'teams.microsoft.com', 'teams.live.com']
    
    for url in urls:
        candidate = None
        
        # Check if it's an Outlook Safelink
        if "safelinks.protection.outlook.com" in url or "url=" in url.lower():
            try:
                parsed = urllib.parse.urlparse(url)
                params = urllib.parse.parse_qs(parsed.query)
                # 'url' param usually contains the original link
                inner_url = params.get('url', [None])[0]
                if inner_url:
                    for p in platforms:
                        if p in inner_url.lower():
                            candidate = inner_url
                            break
            except Exception: pass
            
        # Check directly if not a safelink or safelink parsing failed
        if not candidate:
            for p in platforms:
                if p in url.lower():
                    candidate = url
                    break
        
        if candidate:
            # Clean up trailing characters (sometimes regex captures too much)
            if candidate.endswith(('"', "'", ")", "]", ".")):
                candidate = candidate[:-1]
            return candidate
            
    return None

def _extract_email(o):
    """Deeply extracts email from various nested formats."""
    if not o: return None
    if isinstance(o, str): return o.strip().lower()
    if isinstance(o, list) and len(o) > 0: return _extract_email(o[0])
    if isinstance(o, dict):
        # Try common keys
        res = _get_val(o, ["email", "address", "emailAddress", "email_address"])
        if res:
            if isinstance(res, dict): return _extract_email(res)
            return str(res).strip().lower()
    return None

def process_outlook_webhook(data: dict) -> dict:
    """
    Main entry point for processing webhook data from Make.com.
    Orchestrates: Parser -> DB -> AI -> WhatsApp -> Background Sync (Aux/Bot).
    """
    logging.info("=" * 60)
    logging.info("[OUTLOOK WEBHOOK] Received new webhook")
    logging.info(f"[OUTLOOK WEBHOOK] Payload Keys: {list(data.keys())}")
    logging.info(f"[OUTLOOK WEBHOOK] Full Payload: {data}")

    # 1. Extract Meeting Data
    meeting_raw = _get_val(data, ["meeting", "Meeting Payload", "event", "payload"])
    if not meeting_raw:
        logging.error(f"[OUTLOOK WEBHOOK] ERROR: Missing meeting data. Payload: {data}")
        return {"status": "ignored", "message": "Missing meeting data"}, 200

    # 1.5 Extract Meeting ID early for deduplication
    mtg_id = _get_val(meeting_raw, ["meeting_id", "id", "eventId", "outlook_id"])
    if not mtg_id:
        import uuid
        mtg_id = f"gen_{str(uuid.uuid4())[:8]}"
        logging.warning(f"[OUTLOOK WEBHOOK] No meeting ID found, generated fallback: {mtg_id}")
    else:
        logging.info(f"[OUTLOOK WEBHOOK] Meeting ID: {mtg_id}")

    # Deduplication Check
    existing_mtg = db.execute_query("SELECT id FROM meetings WHERE outlook_event_id = ?", (mtg_id,), fetch_one=True)
    if existing_mtg:
        logging.info(f"[OUTLOOK WEBHOOK] Meeting {mtg_id} already exists (ID: {existing_mtg['id']}). Skipping duplicate processing.")
        return {"status": "success", "message": "Duplicate meeting skipped"}, 200

    # 2. Extract Organizer (Salesperson)
    organizer = _get_val(meeting_raw, ["organizer", "organizer_email", "owner", "organizer_address"])
    org_email = _extract_email(organizer)
    
    logging.info(f"[OUTLOOK WEBHOOK] Raw Organizer Data: {organizer}")
    
    if not org_email:
        # Fallback: check if it's a field directly in meeting_raw
        org_email = _get_val(meeting_raw, ["organizer_email", "organizerEmail"])

    logging.info(f"[OUTLOOK WEBHOOK] Extracted Organizer Email: {org_email}")

    # 3. Identify Salesperson (User)
    user = db.execute_query("SELECT phone, timezone FROM users WHERE email = ?", (org_email,), fetch_one=True)
    if not user:
        registered_users = [r['email'] for r in db.execute_query('SELECT email FROM users', fetch_all=True)]
        logging.warning(f"[OUTLOOK WEBHOOK] ERROR: Organizer {org_email} not registered. Registered users: {registered_users}")
        return {"status": "ignored", "message": f"Organizer {org_email} not registered"}, 200

    sp_phone = user['phone']
    sp_timezone = user['timezone']
    logging.info(f"[OUTLOOK WEBHOOK] Found Salesperson: {org_email} -> Phone: {sp_phone}, Timezone: {sp_timezone}")

    # 4. Extract Client Data
    client_raw = _get_val(data, ["client", "Client", "participant", "contact"])
    c_email = _extract_email(client_raw)
    
    if not c_email:
        # Look in attendees
        attendees = _get_val(meeting_raw, ["attendees"], [])
        if isinstance(attendees, list) and len(attendees) > 0:
            # Pick first attendee that isn't the organizer
            for att in attendees:
                ae = _extract_email(att)
                if ae and ae != org_email:
                    c_email = ae
                    logging.info(f"Found client email in attendees: {c_email}")
                    break

    c_name = _get_val(client_raw, ["name", "displayName", "fullName", "first_name"], "Valued Client")
    logging.info(f"Client Identified: {c_name} <{c_email}>")

    # 5. DB & HubSpot Sync (Pre-Coaching)
    client_id = None
    if c_email:
        c_exist = db.execute_query("SELECT id FROM clients WHERE email = ?", (c_email,), fetch_one=True)
        if c_exist:
            client_id = c_exist['id']
            db.execute_query("UPDATE clients SET name=? WHERE email=?", (c_name, c_email), commit=True)
        else:
            db.execute_query("INSERT INTO clients (email, name) VALUES (?, ?)", (c_email, c_name), commit=True)
            res = db.execute_query("SELECT id FROM clients WHERE email = ?", (c_email,), fetch_one=True)
            client_id = res['id']

    hs_context_str = ""
    if client_id and c_email:
        try:
            hubspot_service = __import__('services.hubspot_service', fromlist=['create_or_find_contact', 'get_contact_details'])
            hs_contact_id = hubspot_service.create_or_find_contact(c_email, c_name, _get_val(client_raw, ["phone", "phoneNumber"], ""))
            if hs_contact_id:
                db.execute_query("UPDATE clients SET hubspot_contact_id = ? WHERE id = ?", (hs_contact_id, client_id), commit=True)
                hs_details = hubspot_service.get_contact_details(hs_contact_id)
                if hs_details:
                    hs_context_str = "\n\n[HubSpot context]\n"
                    for k in ['jobtitle', 'company', 'industry', 'lifecyclestage']:
                        if hs_details.get(k): hs_context_str += f"{k.capitalize()}: {hs_details.get(k)}\n"
        except Exception as e:
            logging.error(f"HubSpot Enrichment Error: {e}")

    # 6. Prepare Coaching Plan
    start_str = _get_val(meeting_raw, ["start_time", "startDateTime", "start"])
    logging.info(f"[OUTLOOK WEBHOOK] Raw Start Time String: {start_str}")
    
    start_dt = parse_iso_datetime(start_str) if start_str else get_current_utc_time()
    logging.info(f"[OUTLOOK WEBHOOK] Parsed Start Time (UTC): {start_dt}")
    
    # Body parsing
    body_obj = _get_val(meeting_raw, ["body", "content", "description"])
    logging.info(f"[OUTLOOK WEBHOOK] Raw Body Object: {body_obj}")
    
    if isinstance(body_obj, dict):
        meeting_body = body_obj.get("content") or body_obj.get("Content") or ""
    else:
        meeting_body = str(body_obj or "")
    
    meeting_body += hs_context_str
    
    loc_obj = _get_val(meeting_raw, ["location", "place"])
    location_str = loc_obj.get("display_name") if isinstance(loc_obj, dict) else str(loc_obj or "Online")
    logging.info(f"[OUTLOOK WEBHOOK] Location: {location_str}")

    # Time display
    _local_start = to_local_time(start_dt, tz_str=sp_timezone)
    display_time = _local_start.strftime('%b %d, %I:%M %p %Z')

    mtg_title = _get_val(meeting_raw, ["title", "subject"], "Sales Meeting")
    logging.info(f"[OUTLOOK WEBHOOK] Meeting Title: {mtg_title}")

    # SAFE AI GENERATION: Don't let 429 quota errors break the code
    coaching = None
    try:
        logging.info(f"[OUTLOOK WEBHOOK] Generating AI coaching for '{mtg_title}'...")
        coaching = ai_service.generate_coaching_plan(
            meeting_title=mtg_title,
            client_name=c_name,
            client_company=_get_val(client_raw, ["company"], "Prospect"),
            start_time=display_time,
            meeting_body=meeting_body,
            location=location_str
        )
        logging.info(f"[OUTLOOK WEBHOOK] AI Coaching generated successfully")
    except Exception as ai_err:
        logging.error(f"[OUTLOOK WEBHOOK] AI Coaching Generation Failed: {ai_err}")
        coaching = {
            "greeting": f"Hello! Ready for your meeting with {c_name}?",
            "scenario": "Upcoming Sales Call",
            "steps": ["Review recent notes", "Confirm meeting link", "Set clear objectives"],
            "recommended_reply": "Looking forward to our chat!"
        }

    # 7. SEND COACHING (Priority)
    msg_body = (
        f"🚀 *New Meeting: {mtg_title}*\n"
        f"{coaching.get('greeting')}\n\n"
        f"🎯 *Scenario*: {coaching.get('scenario')}\n\n"
        f"📋 *Prep Steps*:\n" + "\n".join(f"- {s}" for s in coaching.get("steps", [])) + "\n\n"
        f"💡 *Reply*: {coaching.get('recommended_reply')}"
    )
    
    template_vars = {
        "1": f"🚀 *{mtg_title}*",
        "2": f"{coaching.get('greeting')}\n\n🎯 {coaching.get('scenario')}",
        "3": f"📋 *Steps*:\n" + "\n".join(f"- {s}" for s in coaching.get("steps", []))[:200],
        "4": f"💡 {coaching.get('recommended_reply')}"
    }
    
    whatsapp_service.send_whatsapp_message(sp_phone, body=msg_body, use_template=True, template_vars=template_vars)
    logging.info(f"[OUTLOOK WEBHOOK] Coaching WhatsApp message sent to {sp_phone}")

    # 8. POST-COACHING TASKS (Save & Bot Join)
    # mtg_id is already extracted at step 1.5

    # Extract end time
    end_str = _get_val(meeting_raw, ["end_time", "endDateTime", "end"])
    logging.info(f"[OUTLOOK WEBHOOK] Raw End Time String: {end_str}")
    
    end_dt = parse_iso_datetime(end_str) if end_str else (start_dt + timedelta(minutes=30))
    logging.info(f"[OUTLOOK WEBHOOK] Parsed End Time (UTC): {end_dt}")

    # No need for existing_mtg check here anymore as it was handled early
    logging.info(f"[OUTLOOK WEBHOOK] Inserting new meeting to DB: outlook_id={mtg_id}, start={start_dt}, end={end_dt}, client={client_id}")
    db.execute_query(
        "INSERT INTO meetings (outlook_event_id, start_time, end_time, client_id, status, salesperson_phone, location, title) VALUES (?, ?, ?, ?, 'scheduled', ?, ?, ?)",
        (mtg_id, start_dt, end_dt, client_id, sp_phone, location_str, mtg_title),
        commit=True
    )
    logging.info(f"[OUTLOOK WEBHOOK] Meeting saved to DB successfully")

    # 9. Bot Join Scheduling
    meeting_link = _get_val(meeting_raw, ["online_meeting_url", "join_url", "onlineMeetingUrl"])
    logging.info(f"[OUTLOOK WEBHOOK] Raw meeting link from online_meeting_url: {meeting_link}")
    
    if not meeting_link:
        search_text = f"{location_str} {meeting_body}"
        logging.info(f"[OUTLOOK WEBHOOK] No direct link, searching in: {search_text[:200]}...")
        meeting_link = _extract_meeting_link(search_text)
        logging.info(f"[OUTLOOK WEBHOOK] Extracted meeting link from text: {meeting_link}")

    if meeting_link:
        try:
            import pytz
            start_dt_utc = start_dt.astimezone(pytz.utc) if start_dt.tzinfo else pytz.utc.localize(start_dt)
            scheduled_time_str = start_dt_utc.strftime("%Y-%m-%dT%H:%M:%S+00:00")
            
            logging.info("=" * 60)
            logging.info(f"[BOT SCHEDULING] Attempting to schedule bot join")
            logging.info(f"[BOT SCHEDULING] Meeting Link: {meeting_link}")
            logging.info(f"[BOT SCHEDULING] Scheduled Time (UTC): {scheduled_time_str}")
            logging.info(f"[BOT SCHEDULING] Title: {mtg_title}")
            
            aux_res = aux_service.schedule_meeting(meeting_link, scheduled_time_str, mtg_title, attendee_name="Rolplay (AI Coach)")
            
            if aux_res:
                logging.info(f"[BOT SCHEDULING] SUCCESS! Aux ID: {aux_res.get('meetingId')}, Token: {aux_res.get('token')}")
                db.execute_query("UPDATE meetings SET aux_meeting_id=?, aux_meeting_token=? WHERE outlook_event_id=?", 
                               (aux_res.get("meetingId"), aux_res.get("token"), mtg_id), commit=True)
                logging.info(f"[BOT SCHEDULING] DB updated with aux_meeting_id and aux_meeting_token")
            else:
                logging.error(f"[BOT SCHEDULING] FAILED! aux_service.schedule_meeting returned None for '{mtg_title}'")
        except Exception as e:
            logging.error(f"[BOT SCHEDULING] EXCEPTION: {e}")
            import traceback
            logging.error(f"[BOT SCHEDULING] Traceback: {traceback.format_exc()}")
    else:
        logging.warning(f"[BOT SCHEDULING] SKIPPED - No meeting link found for '{mtg_title}'")

    logging.info("=" * 60)
    logging.info("[OUTLOOK WEBHOOK] Processing completed successfully")
    logging.info("=" * 60)
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
                msg = f"📝 *Meeting Summary Ready ({cname})*\n\n{summary_text[:500]}...\n\n🔗 {report_url}"
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
        hubspot_service = __import__('services.hubspot_service', fromlist=['sync_note_to_contact'])
        hubspot_service.sync_note_to_contact(m['client_id'], f"Feedback: {message_body}")
        
        return "✅ Meeting marked as completed notes synced to CRM."
    
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
            # Use per-user timezone — falls back to APP_TIMEZONE then UTC
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
        return {"status": "error", "message": "Missing title, time, or url"}

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
    meeting_id = meeting_row.get('id', 'unknown')
    logging.info("=" * 60)
    logging.info(f"[AUX TRANSCRIPT] process_aux_transcript() called for meeting {meeting_id}")
    logging.info(f"[AUX TRANSCRIPT] Aux data keys: {list(aux_data.keys()) if isinstance(aux_data, dict) else 'not a dict'}")
    
    transcript_info = aux_data.get("transcript", {})
    content = transcript_info.get("content", "")
    title = aux_data.get("title", "Aux Meeting")
    
    logging.info(f"[AUX TRANSCRIPT] Transcript title: {title}")
    logging.info(f"[AUX TRANSCRIPT] Transcript content length: {len(content) if content else 0} chars")
    
    if not content:
        logging.warning(f"[AUX TRANSCRIPT] No transcript content for Aux meeting {meeting_id}")
        return False
    
    logging.info(f"[AUX TRANSCRIPT] Calling process_transcript_data()...")
    res = process_transcript_data(meeting_row, content, title, source="aux_api")
    success = res.get("status") == "processed"
    logging.info(f"[AUX TRANSCRIPT] Processing result: {success}, full response: {res}")
    logging.info("=" * 60)
    return success


def process_transcript_data(meeting_row, transcript_content, title, source, transcript_url=None):
    """
    Core logic to parse, store, analyze and notify regarding a transcript.
    """
    meeting_id = meeting_row['id']
    logging.info("=" * 60)
    logging.info(f"[TRANSCRIPT DATA] Processing transcript for meeting {meeting_id} from {source}")
    logging.info(f"[TRANSCRIPT DATA] Meeting title: {title}")
    logging.info(f"[TRANSCRIPT DATA] Content length: {len(transcript_content) if transcript_content else 0} chars")
    logging.info(f"[TRANSCRIPT DATA] Transcript URL: {transcript_url}")
    
    # 1. Parse
    logging.info(f"[TRANSCRIPT DATA] Step 1: Parsing transcript...")
    lines = transcript_service.parse_transcript(transcript_content)
    logging.info(f"[TRANSCRIPT DATA] Parsed {len(lines)} lines")
    if lines:
        logging.info(f"[TRANSCRIPT DATA] First 3 lines: {lines[:3]}")
    
    # 2. Store
    logging.info(f"[TRANSCRIPT DATA] Step 2: Storing transcript to DB...")
    transcript_service.store_transcript(meeting_id, lines, source=source)
    logging.info(f"[TRANSCRIPT DATA] Stored {len(lines)} lines of transcript for meeting {meeting_id}")
    
    # 3. Analyze (SAFE AI CALL)
    logging.info(f"[TRANSCRIPT DATA] Step 3: Generating AI analysis...")
    full_text = transcript_service.get_full_transcript_text(lines)
    logging.info(f"[TRANSCRIPT DATA] Full text length for AI: {len(full_text)} chars")
    
    analysis = None
    try:
        analysis = ai_service.generate_post_meeting_analysis(full_text)
        logging.info(f"[TRANSCRIPT DATA] AI analysis generated successfully")
        logging.info(f"[TRANSCRIPT DATA] Analysis keys: {list(analysis.keys()) if isinstance(analysis, dict) else 'not a dict'}")
    except Exception as e:
        logging.error(f"[TRANSCRIPT DATA] Post-meeting AI analysis failed for meeting {meeting_id}: {e}")
        import traceback
        logging.error(f"[TRANSCRIPT DATA] Traceback: {traceback.format_exc()}")

    # 4. Notify
    phone = meeting_row['salesperson_phone']
    logging.info(f"[TRANSCRIPT DATA] Step 4: Notification - salesperson_phone: {phone}")
    
    if phone and analysis:
        try:
            # Format Report
            objections = "\n".join([f"• \"{o['quote']}\"" for o in analysis.get('objections', [])]) or "None detected."
            next_steps = "\n".join([f"• {s}" for s in analysis.get('follow_up_actions', [])])
            
            logging.info(f"[TRANSCRIPT DATA] Buying signals: {len(analysis.get('buying_signals', []))}")
            logging.info(f"[TRANSCRIPT DATA] Risks: {len(analysis.get('risks', []))}")
            logging.info(f"[TRANSCRIPT DATA] Follow-up actions: {len(analysis.get('follow_up_actions', []))}")
            
            template_vars = {
                "1": f"🧠 *Post-Meeting Analysis ({title})*",
                "2": f"🛑 *Objections*:\n{objections}\n\n📈 *Buying Signals*: {len(analysis.get('buying_signals', []))} detected",
                "3": f"⚠️ *Risks*: {len(analysis.get('risks', []))} identified\n\n🚀 *Next Steps*:\n{next_steps}",
                "4": "👉 Reply *Done* after you have followed up."
            }
            
            msg_body = (
                f"🧠 *Post-Meeting Analysis ({title})*\n\n"
                f"🛑 *Objections*:\n{objections}\n\n"
                f"📈 *Buying Signals*: {len(analysis.get('buying_signals', []))} detected\n"
                f"⚠️ *Risks*: {len(analysis.get('risks', []))} identified\n\n"
                f"🚀 *Next Steps*:\n{next_steps}\n\n"
                f"👉 Reply *Done* after you have followed up."
            )
            
            logging.info(f"[TRANSCRIPT DATA] Sending WhatsApp notification to {phone}")
            whatsapp_service.send_whatsapp_message(
                phone,
                body=msg_body,
                use_template=True,
                template_vars=template_vars
            )
            logging.info(f"[TRANSCRIPT DATA] WhatsApp notification sent successfully")
        except Exception as notify_err:
            logging.error(f"[TRANSCRIPT DATA] Failed to send post-meeting notification: {notify_err}")
            import traceback
            logging.error(f"[TRANSCRIPT DATA] Notification traceback: {traceback.format_exc()}")
    else:
        if not phone:
            logging.warning(f"[TRANSCRIPT DATA] No salesperson_phone found, skipping notification")
        if not analysis:
            logging.warning(f"[TRANSCRIPT DATA] No AI analysis generated, skipping notification")

    # 5. Log to HubSpot (SAFE SYNC)
    if analysis:
        try:
            logging.info(f"[TRANSCRIPT DATA] Step 5: Syncing to HubSpot...")
            hubspot_service = __import__('services.hubspot_service', fromlist=['sync_meeting_analysis'])
            hubspot_service.sync_meeting_analysis(
                client_db_id=meeting_row['client_id'],
                meeting_title=title,
                analysis=analysis,
                transcript_url=transcript_url or "Stored in Database"
            )
            logging.info(f"[TRANSCRIPT DATA] HubSpot sync completed")
        except Exception as e:
            logging.error(f"[TRANSCRIPT DATA] HubSpot Analysis Sync Failed: {e}")
            import traceback
            logging.error(f"[TRANSCRIPT DATA] HubSpot traceback: {traceback.format_exc()}")
    else:
        logging.info(f"[TRANSCRIPT DATA] Skipping HubSpot sync (no analysis)")
    
    logging.info(f"[TRANSCRIPT DATA] Processing complete for meeting {meeting_id}")
    logging.info("=" * 60)
    return {"status": "processed", "meeting_id": meeting_id}
