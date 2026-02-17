import os
import logging
from flask import Flask, request, jsonify, Response
from dotenv import load_dotenv

load_dotenv()

from twilio.twiml.messaging_response import MessagingResponse

from database import db
from services import meeting_service, whatsapp_service, ai_service, parsing_service, hubspot_service
from utils import normalize_phone
import scheduler
import json

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

app = Flask(__name__)

db.init_db()
scheduler.start_scheduler()

@app.route('/health', methods=['GET'])
def health():
    db_mode = 'Postgres' if db.is_postgres else 'SQLite'
    try:
        users = db.execute_query("SELECT count(*) as c FROM users", fetch_one=True)
        count = users['c'] if users else 0
        debug_info = {
            "status": "online",
            "db_mode": db_mode,
            "user_count": count
        }
        return jsonify(debug_info), 200
    except Exception as e:
        return jsonify({"status": "error", "db_mode": db_mode, "error": str(e)}), 500

@app.route('/setup', methods=['GET'])
def setup_page():
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
                    Register
                </button>
            </form>
        </div>
    </body>
    </html>
    """

@app.route('/register', methods=['POST'])
def register():
    try:
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        raw_phone = request.form.get("phone", "")
        
        phone = normalize_phone(raw_phone)
        
        # Check if user exists
        existing = db.execute_query("SELECT email, hubspot_contact_id FROM users WHERE email = ?", (email,), fetch_one=True)
        
        # Try to create or find HubSpot contact
        hubspot_contact_id = None
        try:
            hubspot_contact_id = hubspot_service.create_or_find_contact(email, name, phone)
            if hubspot_contact_id:
                logging.info(f"HubSpot contact synced for {email}: {hubspot_contact_id}")
        except Exception as e:
            logging.warning(f"HubSpot sync failed for {email}: {e}")
        
        # Save to database
        if existing:
            db.execute_query("UPDATE users SET name = ?, phone = ?, hubspot_contact_id = ? WHERE email = ?", 
                           (name, phone, hubspot_contact_id, email), commit=True)
        else:
            db.execute_query("INSERT INTO users (email, name, phone, hubspot_contact_id) VALUES (?, ?, ?, ?)", 
                           (email, name, phone, hubspot_contact_id), commit=True)
        
        # Get bot email addresses from environment
        bot_email_primary = os.getenv("BOT_EMAIL_PRIMARY", "bhattacharyabuddhadeb147@gmail.com")
        bot_email_secondary = os.getenv("BOT_EMAIL_SECONDARY", "bhattacharyabuddhadeb@outlook.com")
        msg = (f"🎉 Welcome {name}! You are registered.\n\n"
               f"To receive coaching, invite BOTH bot accounts to your meetings:\n"
               f"• {bot_email_primary}\n"
               f"• {bot_email_secondary}")
        whatsapp_service.send_whatsapp_message(phone, msg)
        
        return f"<h1>Success!</h1><p>{name} is registered. Check WhatsApp for confirmation.</p>"
    except Exception as e:
        logging.error(f"Registration Error: {e}")
        return f"Error: {e}", 400

@app.route('/outlook-webhook', methods=['POST'])
def outlook_webhook():
    data = request.json
    if not data:
        return jsonify({"error": "No data"}), 400
    
    try:
        result = meeting_service.process_outlook_webhook(data)
        return jsonify(result), 200
    except Exception as e:
        logging.error(f"Webhook Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/read-ai-webhook', methods=['POST'])
def read_ai_webhook():
    data = request.json
    if not data:
        return jsonify({"error": "No data"}), 400
    
    try:
        meeting_service.process_read_ai_webhook(data)
        return jsonify({"status": "received"}), 200
    except Exception as e:
        logging.error(f"Read AI Webhook Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/whatsapp-webhook', methods=['POST'])
def whatsapp_webhook():
    sender = request.values.get('From', '')
    body = request.values.get('Body', '').strip()
    
    response_text = meeting_service.handle_incoming_message(sender, body)
    
    resp = MessagingResponse()
    resp.message(response_text)
    return Response(str(resp), mimetype="text/xml")

@app.route('/readai-webhook', methods=['POST'])
def readai_ingest_webhook():
    data = request.json
    if not data:
        return jsonify({"error": "No data"}), 400
        
    try:
        # Support both Read.ai format and Aux format
        if "meeting" in data and "transcript" in data["meeting"]:
            result = meeting_service.process_aux_transcript({}, data["meeting"])
            return jsonify({"status": "success", "source": "aux_api_detected"}), 200
            
        result = meeting_service.process_transcript_webhook(data)
        return jsonify(result), 200
    except Exception as e:
        logging.error(f"ReadAI Ingest Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/ingest-raw-meeting', methods=['POST'])
def ingest_raw_meeting():
    data = request.json or {}
    # RELAXED CHECK: Support multiple key variations
    raw_text = data.get('raw_text') or data.get('Raw text') or data.get('text') or ""
    
    logging.info(f"Ingest Raw Text Length: {len(raw_text)}")
    logging.info(f"Ingest Raw Text Snippet: {raw_text[:200]}")
    
    # Support for Aux API JSON format if sent here
    if not raw_text and "meeting" in data:
        mtg = data["meeting"]
        raw_text = mtg.get("transcript", {}).get("content", "")
        if raw_text:
             logging.info("Detected Aux API JSON structure in raw ingest")
    
    if not raw_text:
        logging.warning(f"Ingest received empty raw_text. Keys received: {list(data.keys())}")
    
    session_id = data.get("session_id") # Support explicit session_id
    transcript = ""
    summary = data.get("summary")
    
    # 1. PARSING (Robust)
    try:
        parsed = parsing_service.parse_raw_meeting_text(raw_text)
        session_id = parsed.get('session_id')
        transcript = parsed.get('transcript') or ""
        summary = parsed.get('summary')
    except Exception as e:
        logging.error(f"Parsing failed completely: {e}")
        # Fallback if parsing crashes
        import uuid
        session_id = f"crash_fallback_{str(uuid.uuid4())[:8]}"
        transcript = raw_text

    # Double check session_id
    if not session_id:
        import uuid
        import time
        session_id = f"fallback_{int(time.time())}_{str(uuid.uuid4())[:8]}"
        logging.warning(f"Generated fallback session_id: {session_id}")

    # 2. DATABASE SAVE (Critical)
    try:
        existing = db.execute_query(
            "SELECT id FROM meeting_coaching WHERE session_id = ?", 
            (session_id,), 
            fetch_one=True
        )
        
        if existing:
            db.execute_query(
                "UPDATE meeting_coaching SET transcript = ?, summary = ? WHERE session_id = ?",
                (transcript, summary, session_id),
                commit=True
            )
        else:
            db.execute_query(
                "INSERT INTO meeting_coaching (session_id, transcript, summary, source) VALUES (?, ?, ?, ?)",
                (session_id, transcript, summary, "raw_ingest"),
                commit=True
            )
    except Exception as e:
        logging.error(f"DB Save Failed: {e}")
        # If we can't save to DB, we really can't proceed much, but let's try to notify anyway? 
        # Usually 500 is appropriate here, but let's return 200 with error note to not break Make.com
        return jsonify({"status": "partial_success", "error": "database_failed", "message": str(e)}), 200
    
    # 3. AI COACHING (Optional Component)
    coaching_json = {}
    try:
        # Ensure transcript is safe
        safe_transcript = transcript if transcript else "No transcript available."
        coaching_json = ai_service.generate_sales_coaching(safe_transcript)
        
        # Save Result
        coaching_str = json.dumps(coaching_json)
        db.execute_query(
            "UPDATE meeting_coaching SET coaching = ? WHERE session_id = ?",
            (coaching_str, session_id),
            commit=True
        )
    except Exception as e:
        logging.error(f"AI Coaching Generation Failed: {e}")
        # Create dummy coaching so notification doesn't break
        coaching_json = {
            "strengths": ["Data received"],
            "weaknesses": ["AI analysis pending/failed"],
            "recommended_actions": ["Check logs"]
        }

    # 4. NOTIFICATION (Optional Component)
    notified = False
    try:
        target_phone = None
        
        # A. Try Owner Email from Parse
        owner_email = parsed.get('owner_email') if 'parsed' in locals() else None
        if owner_email:
            u = db.execute_query("SELECT phone FROM users WHERE email = ?", (owner_email,), fetch_one=True)
            if u:
                target_phone = u['phone']
                logging.info(f"Targeting Owner: {owner_email} -> {target_phone}")
        
        if not target_phone:
            # B1. Try matching Speaker Names to Registered Users (Fuzzy/Exact)
            speaker_blocks = parsed.get("speaker_blocks", [])
            unique_speakers = set(b.get("speaker", "").lower() for b in speaker_blocks if b.get("speaker"))
            
            if unique_speakers:
                # Get all users to check against
                all_users = db.execute_query("SELECT name, phone FROM users", fetch_all=True)
                if all_users:
                    for u in all_users:
                        if u['name'] and u['name'].lower() in unique_speakers:
                            target_phone = u['phone']
                            logging.info(f"Targeting Matched Speaker: {u['name']} -> {target_phone}")
                            break

        if not target_phone:
            # B. Try matching with recent meeting
            recent_mtg = db.execute_query(
                "SELECT id, salesperson_phone FROM meetings WHERE status IN ('scheduled', 'reminder_sent') ORDER BY id DESC LIMIT 1",
                fetch_one=True
            )
            if recent_mtg and recent_mtg['salesperson_phone']:
                target_phone = recent_mtg['salesperson_phone']
                logging.info(f"Targeting Recent Meeting Owner: {target_phone}")
                
                 # Link Ingested Summary
                if summary:
                    db.execute_query("UPDATE meetings SET summary = ? WHERE id = ?", (summary, recent_mtg['id']), commit=True)
            
        # C. Fallback: First Registered User
        if not target_phone:
            user = db.execute_query("SELECT phone FROM users LIMIT 1", fetch_one=True)
            if user:
                target_phone = user['phone']

        if target_phone:
            strengths = "\n".join([f"✅ {s}" for s in coaching_json.get("strengths", [])[:2]])
            weaknesses = "\n".join([f"⚠️ {w}" for w in coaching_json.get("weaknesses", [])[:2]])
            tips = "\n".join([f"💡 {t}" for t in coaching_json.get("recommended_actions", [])[:2]])
            
            # Format Title (Hide ID if fallback/demo)
            title_suffix = ""
            if session_id and not session_id.startswith(("demo_", "fallback_", "crash_")):
                title_suffix = f" ({session_id})"
            
            msg = (
                f"🚀 *Post-Meeting Coaching{title_suffix}*\n\n"
                f"*Strengths*:\n{strengths}\n\n"
                f"*Improvements*:\n{weaknesses}\n\n"
                f"*Action Plan*:\n{tips}\n\n"
                f"👉 Reply *Done* to log this to HubSpot."
            )
            whatsapp_service.send_whatsapp_message(target_phone, msg)
            logging.info(f"Sent raw ingest coaching to {target_phone}")
            notified = True
        else:
            logging.warning("No user found to notify.")
            
    except Exception as e:
        logging.error(f"Notification Failed: {e}")

    return jsonify({
        "status": "success",
        "session_id": session_id,
        "notified": notified,
        "notes": "Processed with robust fallbacks"
    }), 200


@app.route('/api/post-meeting-coaching', methods=['POST'])
def post_meeting_coaching_endpoint():
    data = request.json
    if not data:
        return jsonify({"error": "No data"}), 400
        
    session_id = data.get("session_id")
    transcript = data.get("transcript")
    title = data.get("title", "Untitled Session")
    source = data.get("source", "read.ai")
    
    if not session_id or not transcript:
        return jsonify({"error": "Missing session_id or transcript"}), 400
        
    try:
        # Check existing
        existing = db.execute_query("SELECT id FROM meeting_coaching WHERE session_id = ?", (session_id,), fetch_one=True)
        
        if existing:
            db.execute_query(
                "UPDATE meeting_coaching SET transcript = ?, title = ? WHERE session_id = ?",
                (transcript, title, session_id),
                commit=True
            )
        else:
            db.execute_query(
                "INSERT INTO meeting_coaching (session_id, title, transcript, source) VALUES (?, ?, ?, ?)",
                (session_id, title, transcript, source),
                commit=True
            )
            
        # 3. Generate AI Coaching
        # ai_service is already imported
        import json
        
        coaching_json = ai_service.generate_sales_coaching(transcript)
        
        # 4. Save Coaching Result
        coaching_str = json.dumps(coaching_json)
        
        db.execute_query(
            "UPDATE meeting_coaching SET coaching = ? WHERE session_id = ?",
            (coaching_str, session_id),
            commit=True
        )
        
        # 5. Return Response
        return jsonify({
            "success": True,
            "session_id": session_id,
            "coaching": coaching_json
        }), 200
        
    except Exception as e:
        logging.error(f"Post-Meeting Coaching Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/survey-completed', methods=['POST'])
def survey_completed_webhook():
    """
    Webhook endpoint to receive survey completion notifications from the external survey system.
    Syncs survey responses to HubSpot as notes on the participant's contact.
    
    Expected payload:
    {
        "participant_email": "jane@example.com",
        "participant_name": "Jane Doe",
        "meeting_title": "Demo Meeting",
        "session_id": "unique-session-id",
        "survey_response": {
            "punctuality": 5,
            "listening_understanding": 5,
            "knowledge_expertise": 4,
            "clarity_answers": 5,
            "overall_value": 5,
            "most_valuable": "Great insights",
            "improvements": "More examples needed"
        },
        "submitted_at": "2025-12-22T10:30:00Z"
    }
    """
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    try:
        participant_email = data.get("participant_email")
        if not participant_email:
            return jsonify({"error": "Missing participant_email"}), 400
        
        survey_response = data.get("survey_response", {})
        if not survey_response:
            return jsonify({"error": "Missing survey_response"}), 400
        
        # Combine data for HubSpot sync
        survey_data = {
            **survey_response,
            "participant_name": data.get("participant_name"),
            "meeting_title": data.get("meeting_title"),
            "session_id": data.get("session_id"),
            "submitted_at": data.get("submitted_at")
        }
        
        # Sync to HubSpot (non-blocking - don't fail webhook if HubSpot fails)
        sync_success = hubspot_service.sync_survey_response_to_contact(participant_email, survey_data)
        
        if sync_success:
            logging.info(f"Survey response synced to HubSpot for {participant_email}")
        else:
            logging.warning(f"Survey response received but HubSpot sync failed for {participant_email}")
        
        # Always return success to survey system (fire-and-forget pattern)
        return jsonify({
            "status": "received",
            "hubspot_synced": sync_success,
            "participant_email": participant_email
        }), 200
        
    except Exception as e:
        logging.error(f"Survey Webhook Error: {e}")
        # Return 200 even on error to prevent survey system retry loops
        return jsonify({
            "status": "received",
            "hubspot_synced": False,
            "error": str(e)
        }), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
