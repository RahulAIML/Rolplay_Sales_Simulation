import os
import json
import logging
# import sqlite3 - Removed, using database.py
from database import db
import time
from datetime import datetime, timedelta
import pytz
from dateutil import parser
from flask import Flask, request, jsonify, Response
from dotenv import load_dotenv
import google.generativeai as genai
from jsonschema import validate, ValidationError
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
from apscheduler.schedulers.background import BackgroundScheduler
import atexit
from hubspot import HubSpot
from hubspot.crm.objects import SimplePublicObjectInputForCreate

# 1. Setup & Configuration
load_dotenv()

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)

app = Flask(__name__)

# Load secrets
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM")
ADMIN_WHATSAPP_TO = os.getenv("ADMIN_WHATSAPP_TO")
HUBSPOT_ACCESS_TOKEN = os.getenv("HUBSPOT_ACCESS_TOKEN")

# Configure Clients
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.5-flash")

hubspot_client = None
if HUBSPOT_ACCESS_TOKEN:
    try:
        hubspot_client = HubSpot(access_token=HUBSPOT_ACCESS_TOKEN)
    except Exception as e:
        logging.warning(f"HubSpot init failed: {e}")

DB_NAME = "coachlink.db"

# 2. Database Management
# (Handled by database.py)

# 3. Helper Functions
def call_gemini_json(prompt):
    try:
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        text = response.text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        return json.loads(text)
    except Exception as e:
        logging.error(f"Gemini Error: {e}")
        return None

def send_whatsapp(body, to_number):
    try:
        if not to_number: return None
        # Clean the number: remove spaces, dashes, parentheses
        to_number = to_number.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        
        if not to_number.startswith("whatsapp:"):
            to_number = f"whatsapp:{to_number}"
        
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        msg = client.messages.create(
            from_=TWILIO_WHATSAPP_FROM,
            body=body,
            to=to_number
        )
        return msg.sid
    except Exception as e:
        logging.error(f"Twilio Error: {e}")
        return None

from hubspot.crm.contacts import PublicObjectSearchRequest

def sync_to_hubspot(client_id, note_body):
    if not hubspot_client: return
    try:
        # Fetch Client
        row = db.execute_query("SELECT email, hubspot_contact_id FROM clients WHERE id = ?", (client_id,), fetch_one=True)
        
        if not row:
            return
            
        email = row['email']
        hs_id = row['hubspot_contact_id']
        
        # Fallback: Search by Email if ID is missing
        if not hs_id and email:
            try:
                search_req = PublicObjectSearchRequest(
                    filter_groups=[
                        {
                            "filters": [
                                {
                                    "propertyName": "email",
                                    "operator": "EQ",
                                    "value": email
                                }
                            ]
                        }
                    ]
                )
                res = hubspot_client.crm.contacts.search_api.do_search(public_object_search_request=search_req)
                if res.results:
                    hs_id = res.results[0].id
                    # Save back to DB for next time
                    db.execute_query("UPDATE clients SET hubspot_contact_id = ? WHERE id = ?", (hs_id, client_id), commit=True)
                    logging.info(f"✅ Auto-linked HubSpot ID {hs_id} for {email}")
            except Exception as e:
                logging.error(f"HubSpot Search Error: {e}")

        if hs_id:
            properties = {
                "hs_timestamp": datetime.now(pytz.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                "hs_note_body": note_body
            }
            batch_input = SimplePublicObjectInputForCreate(
                properties=properties,
                associations=[{
                    "to": {"id": hs_id},
                    "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 202}]
                }]
            )
            hubspot_client.crm.objects.notes.basic_api.create(
                simple_public_object_input_for_create=batch_input
            )
            logging.info(f"Synced note to HubSpot Contact {hs_id}")
            logging.info("Synced to HubSpot.")
    except Exception as e:
        logging.error(f"HubSpot Sync Error: {e}")

# 4. Scheduler
def check_pending_meetings():
    now_utc = datetime.now(pytz.utc)
    
    meetings = db.execute_query("SELECT * FROM meetings WHERE status = 'scheduled'", fetch_all=True) or []
    
    for m in meetings:
        try:
            # Handle potential milliseconds or timezone suffixes manually if parser fails
            # For start_time
            raw_start_time = m['start_time']
            start_str_cleaned = raw_start_time.replace(' UTC', '').split('.')[0]
            start_dt = parser.parse(start_str_cleaned).replace(tzinfo=pytz.utc)
            
            # For end_time
            if m['end_time']:
                raw_end_time = m['end_time']
                end_str_cleaned = raw_end_time.replace(' UTC', '').split('.')[0]
                end_dt = parser.parse(end_str_cleaned).replace(tzinfo=pytz.utc)
            else:
                end_dt = start_dt + timedelta(minutes=30)
            
            # Reminder: 1 min after meeting end
            if now_utc >= (end_dt + timedelta(minutes=1)):
                 target = m['salesperson_phone'] or ADMIN_WHATSAPP_TO
                 
                 # Get Client Name
                 crow = db.execute_query("SELECT name FROM clients WHERE id = ?", (m['client_id'],), fetch_one=True)
                 cname = crow['name'] if crow else "the client"
                 
                 send_whatsapp(f"🔔 Meeting with {cname} finished. How did it go? (Reply here to log)", target)
                 
                 db.execute_query("UPDATE meetings SET status = 'reminder_sent' WHERE id = ?", (m['id'],), commit=True)
                 
        except Exception as e:
            logging.error(f"Scheduler Error: {e}")

scheduler = BackgroundScheduler()
scheduler.add_job(func=check_pending_meetings, trigger="interval", seconds=60)

if os.environ.get("RENDER") == "true":
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown())

# 5. Routes
@app.route('/health', methods=['GET'])
def health():
    return "OK", 200

@app.route('/register', methods=['POST'])
def register():
    try:
        name = request.form.get("name")
        email = request.form.get("email")
        # Normalize phone on registration
        raw_phone = request.form.get("phone")
        clean = str(raw_phone).replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        # Ensure prefix logic consistent with rest of app
        phone = f"whatsapp:{clean}" if not clean.startswith("whatsapp:") else clean
        
        db.execute_query("INSERT INTO users (email, name, phone) VALUES (?, ?, ?)", (email, name, phone))
        # Note: We rely on unique constraint failure or manual check if needed, but original used INSERT OR REPLACE or just INSERT.
        # SQLite supports INSERT OR REPLACE. Postgres has INSERT ... ON CONFLICT.
        # To be safe for both without writing complex SQL, we can try INSERT and catch error, or delete then insert.
        # Let's use Delete then Insert for max compatibility (though slightly inefficient, it's 1 user).
        
        # Actually, let's just use two steps:
        existing = db.execute_query("SELECT email FROM users WHERE email = ?", (email,), fetch_one=True)
        if existing:
            db.execute_query("UPDATE users SET name = ?, phone = ? WHERE email = ?", (name, phone, email), commit=True)
        else:
            db.execute_query("INSERT INTO users (email, name, phone) VALUES (?, ?, ?)", (email, name, phone), commit=True)
        
        return f"<h1>Success!</h1><p>{name} ({email}) is now registered. Invite 'rahulbhattacharyackt@gmail.com' to your meetings to receive coaching on {phone}.</p>"
    except Exception as e:
        return f"Error: {e}", 400

@app.route('/setup', methods=['GET'])
def setup():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sales AI Config</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-100 min-h-screen flex items-center justify-center">
    <div class="bg-white p-8 rounded-lg shadow-lg w-full max-w-md">
        <h1 class="text-2xl font-bold mb-6 text-center text-blue-600">Connect Sales AI</h1>
        <p class="mb-6 text-gray-600 text-center">Enable AI coaching for your Outlook meetings.</p>
        <form action="/register" method="post" class="space-y-4">
            <div>
                <label class="block text-sm font-medium text-gray-700">Full Name</label>
                <input type="text" name="name" placeholder="John Doe" required 
                       class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 p-2 border">
            </div>
            <div>
                <label class="block text-sm font-medium text-gray-700">Outlook Email</label>
                <input type="email" name="email" placeholder="john.doe@company.com" required 
                       class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 p-2 border">
            </div>
            <div>
                <label class="block text-sm font-medium text-gray-700">WhatsApp Number</label>
                <input type="text" name="phone" placeholder="+1234567890" required 
                       class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 p-2 border">
                <p class="text-xs text-gray-500 mt-1">Include country code (e.g., +1...)</p>
            </div>
            <button type="submit" 
                    class="w-full flex justify-center py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500">
                Register for Coaching
            </button>
        </form>
    </div>
</body>
</html>
"""

@app.route('/outlook-webhook', methods=['POST'])
def outlook_webhook():
    data = request.json
    if not data: return jsonify({"error": "No data"}), 400
    
    logging.info(f"Webhook Data: {data}")
    
    # 1. Parse Data
    meeting = data.get("meeting", {})
    client = data.get("client", {})
    # Default salesperson from Make.com payload (might be None)
    salesperson = data.get("salesperson", {})
    
    # Check for "Invite Method" Override
    sp_phone = None
    try:
        organizer_raw = meeting.get("organizer", "{}")
        if isinstance(organizer_raw, str):
            import json
            org_data = json.loads(organizer_raw)
            org_email = org_data.get("address")
        else:
            org_email = organizer_raw.get("address") # If already dict
            
        if org_email:
            u = db.execute_query("SELECT phone FROM users WHERE email = ?", (org_email,), fetch_one=True)
            if u:
                sp_phone = u['phone']
                logging.info(f"Found registered user for organizer {org_email}: {sp_phone}")
    except Exception as e:
        logging.error(f"Organizer Parsing Error: {e}")

    
    m_title = meeting.get("title", "Meeting")
    m_start = meeting.get("start_time")
    m_end = meeting.get("end_time")
    
    # Normalize Time
    try:
        s_dt = parser.parse(m_start)
        if s_dt.tzinfo is None: s_dt = s_dt.replace(tzinfo=pytz.utc)
        start_str = s_dt.isoformat()
        
        if m_end:
            e_dt = parser.parse(m_end)
            if e_dt.tzinfo is None: e_dt = e_dt.replace(tzinfo=pytz.utc)
            end_str = e_dt.isoformat()
        else:
            end_str = (s_dt + timedelta(minutes=30)).isoformat()
    except:
        start_str = datetime.now(pytz.utc).isoformat()
        end_str = (datetime.now(pytz.utc) + timedelta(minutes=30)).isoformat()

    # 2. Save to DB
    
    # Client
    # Helper to avoid "INSERT OR IGNORE" which is SQLite specific.
    c_exist = db.execute_query("SELECT id FROM clients WHERE email = ?", (client.get("email"),), fetch_one=True)
    
    if c_exist:
        db.execute_query(
            "UPDATE clients SET name=?, company=?, hubspot_contact_id=? WHERE email=?",
            (client.get("name"), client.get("company"), client.get("hubspot_contact_id"), client.get("email")),
            commit=True
        )
        client_id = c_exist['id']
    else:
        # We need ID back. Postgres uses RETURNING id; SQLite uses cursor.lastrowid
        # Our db helper complicates retrieving the ID in a unified way if we just execute.
        # Let's just insert and re-fetch for simplicity/portability
        db.execute_query(
            "INSERT INTO clients (email, name, company, hubspot_contact_id) VALUES (?, ?, ?, ?)",
            (client.get("email"), client.get("name"), client.get("company"), client.get("hubspot_contact_id")),
            commit=True
        )
        res = db.execute_query("SELECT id FROM clients WHERE email = ?", (client.get("email"),), fetch_one=True)
        client_id = res['id']
    
    # Meeting
    sys_id = meeting.get("meeting_id", f"sys_{int(time.time())}")
    
    # Robust Phone Handling
    # If sp_phone was set by Invite Method (above), skip default logic
    if not sp_phone:
        raw_phone = salesperson.get("phone")
        if not raw_phone or "REPLACE_WITH" in str(raw_phone):
            sp_phone = ADMIN_WHATSAPP_TO
        else:
            # Normalize: Clean and ensure prefix
            clean = str(raw_phone).replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
            sp_phone = f"whatsapp:{clean}" if not clean.startswith("whatsapp:") else clean
    
    
    db.execute_query(
        "INSERT INTO meetings (client_id, outlook_event_id, start_time, end_time, status, salesperson_phone) VALUES (?, ?, ?, ?, 'scheduled', ?)",
        (client_id, sys_id, start_str, end_str, sp_phone),
        commit=True
    )
    
    # 3. AI Prep
    prompt = f"""
    You are an expert Sales Coach AI. 
    A salesperson has a new meeting upcoming.
    
    DETAILS:
    - Meeting Title: {m_title}
    - Client Name: {client.get('name')}
    - Client Company: {client.get('company')}
    - Time: {start_str}

    TASK:
    Generate a coaching plan in JSON format.
    1. 'greeting': A motivating, professional greeting.
    2. 'scenario': A 1-sentence summary of what this meeting likely involves based on the title.
    3. 'steps': 3 concise, actionable bullet points for preparation.
    4. 'recommended_reply': A short, professional acknowledgement message the salesperson can say to you (the bot).

    Schema: {{ "greeting": "...", "scenario": "...", "steps": ["...", "...", "..."], "recommended_reply": "..." }}
    """
    ai = call_gemini_json(prompt)
    if not ai: ai = {"greeting":"Hello", "scenario":"Meeting", "steps":[], "recommended_reply":"Ok"}
    
    # 4. Notify
    steps = "\n".join(f"- {s}" for s in ai.get("steps", []))
    msg = f"🚀 *New Meeting*\n{ai.get('greeting')}\nScenario: {ai.get('scenario')}\nSteps:\n{steps}\nReply: {ai.get('recommended_reply')}"
    
    send_whatsapp(msg, sp_phone)
    
    return jsonify({"status": "success"}), 200

@app.route('/whatsapp-webhook', methods=['POST'])
def whatsapp_reply():
    msg = request.values.get('Body', '').strip()
    
    # Fix 7: Debug Logs
    raw_sender = request.values.get('From', '')
    logging.info(f"Incoming raw sender: {raw_sender}")

    # Fix 1 & 3: Strict Normalization (Single Format)
    clean = raw_sender.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
    sender = f"whatsapp:{clean}" if not clean.startswith("whatsapp:") else clean
        
    logging.info(f"Normalized sender: {sender}")
    
    conn = None # conn no longer used, keep for diff safety if needed or just remove.
    
    # Active meeting?
    # Fix 1: Single variant query (since we enforce strict format now)
    # Note: ORDER BY id DESC LIMIT 1 is valid in both SQLite and Postgres
    m = db.execute_query("SELECT * FROM meetings WHERE salesperson_phone = ? AND status IN ('scheduled', 'reminder_sent') ORDER BY id DESC LIMIT 1", (sender,), fetch_one=True)
    
    resp = MessagingResponse()
    
    if m:
        db.execute_query("INSERT INTO messages (client_id, direction, message, timestamp) VALUES (?, 'incoming', ?, ?)",
                  (m['client_id'], msg, datetime.now().isoformat()), commit=True)
        
        if any(w in msg.lower() for w in ['done', 'completed']):
            db.execute_query("UPDATE meetings SET status='completed' WHERE id=?", (m['id'],), commit=True)
            sync_to_hubspot(m['client_id'], f"Feedback: {msg}")
            resp.message("✅ Meeting marked as completed & synced.")
        else:
            # Dynamic AI Reply
            try:
                # Context building
                client = db.execute_query("SELECT name, company FROM clients WHERE id = ?", (m['client_id'],), fetch_one=True)
                c_name = client['name'] if client else "the client"
                
                # Simple chat prompt (not JSON)
                prompt = f"""
                You are a sales coach. The salesperson is in a meeting loop with {c_name}.
                They just said: "{msg}"
                Provide a short, helpful coaching tip or answer. Be concise (under 50 words).
                """
                response = model.generate_content(prompt)
                ai_reply = response.text.strip()
            except Exception as e:
                logging.error(f"Chat AI Error: {e}")
                ai_reply = "Stored. (AI unavailable)"

            resp.message(ai_reply)
    else:
        resp.message("No active meeting config found. (Check 'salesperson_phone' in DB)")
    return Response(str(resp), mimetype="text/xml")

if __name__ == "__main__":
    db.init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
