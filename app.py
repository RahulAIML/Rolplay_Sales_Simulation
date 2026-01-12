import os
import logging
from flask import Flask, request, jsonify, Response
from dotenv import load_dotenv

load_dotenv()

from twilio.twiml.messaging_response import MessagingResponse

from database import db
from services import meeting_service, whatsapp_service, ai_service, parsing_service
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
        name = request.form.get("name")
        email = request.form.get("email")
        raw_phone = request.form.get("phone")
        
        phone = normalize_phone(raw_phone)
        
        existing = db.execute_query("SELECT email FROM users WHERE email = ?", (email,), fetch_one=True)
        if existing:
            db.execute_query("UPDATE users SET name = ?, phone = ? WHERE email = ?", (name, phone, email), commit=True)
        else:
            db.execute_query("INSERT INTO users (email, name, phone) VALUES (?, ?, ?)", (email, name, phone), commit=True)
        
        bot_email = os.getenv("BOT_EMAIL", "bhattacharyabuddhadeb@outlook.com")
        msg = (f"🎉 Welcome {name}! You are registered.\n\n"
               f"Invite '{bot_email}' to your meetings to receive coaching.")
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
        result = meeting_service.process_transcript_webhook(data)
        return jsonify(result), 200
    except Exception as e:
        logging.error(f"ReadAI Ingest Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/ingest-raw-meeting', methods=['POST'])
def ingest_raw_meeting():
    data = request.json
    if not data or 'raw_text' not in data:
        return jsonify({"error": "Missing raw_text field"}), 400
        
    raw_text = data['raw_text']
    
    try:
        parsed = parsing_service.parse_raw_meeting_text(raw_text)
        session_id = parsed.get('session_id')
        transcript = parsed.get('transcript')
        summary = parsed.get('summary')
        
        if not session_id:
            return jsonify({"error": "Could not extract session_id"}), 400
            

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
        
        # --- NEW: Generate Coaching & Notify ---
        # 1. Generate Coaching
        coaching_json = ai_service.generate_sales_coaching(transcript)
        
        # 2. Save Coaching
        coaching_str = json.dumps(coaching_json)
        db.execute_query(
            "UPDATE meeting_coaching SET coaching = ? WHERE session_id = ?",
            (coaching_str, session_id),
            commit=True
        )
        
        # 3. Notify User
        target_phone = None
        
        # A. Try Owner Email from Parse
        owner_email = parsed.get('owner_email')
        if owner_email:
            u = db.execute_query("SELECT phone FROM users WHERE email = ?", (owner_email,), fetch_one=True)
            if u:
                target_phone = u['phone']
                logging.info(f"Targeting Owner: {owner_email} -> {target_phone}")
        
        if not target_phone:
            # 2. Try matching with existing meetings (Best effort by time or similar logic if session_id stored?)
            # Since we don't store session_id in 'meetings' table directly usually, we rely on time matching or if we added columns.
            # But wait! We added logic in 'meeting_service.py' to match Read AI webhooks. 
            # Ideally the raw ingest should link to the meeting too.
            
            # Let's try to match by roughly "now" or if the user passed time? 
            # The raw text doesn't explicitly have time easy to parse unless we add it.
            
            # Fallback: Check if ANY meeting exists for this owner email today? 
            pass
            
        # C. Fallback: First Registered User
        if not target_phone:
            logging.info("Owner not found or not registered. Falling back to first user.")
            user = db.execute_query("SELECT phone FROM users LIMIT 1", fetch_one=True)
            if user:
                target_phone = user['phone']

        if target_phone:
            # Format message with strengths/weaknesses
            strengths = "\n".join([f"✅ {s}" for s in coaching_json.get("strengths", [])[:2]])
            weaknesses = "\n".join([f"⚠️ {w}" for w in coaching_json.get("weaknesses", [])[:2]])
            tips = "\n".join([f"💡 {t}" for t in coaching_json.get("recommended_actions", [])[:2]])
            
            msg = (
                f"🚀 *Post-Meeting Coaching ({session_id})*\n\n"
                f"*Strengths*:\n{strengths}\n\n"
                f"*Improvements*:\n{weaknesses}\n\n"
                f"*Action Plan*:\n{tips}\n\n"
                f"Check dashboard for full details."
            )
            whatsapp_service.send_whatsapp_message(target_phone, msg)
            logging.info(f"Sent raw ingest coaching to {target_phone}")
        else:
            logging.warning("No user found to notify for raw ingest.")

        return jsonify({
            "status": "success",
            "session_id": session_id,
            "notified": bool(target_phone),
            "extracted_data": {
                "summary_length": len(summary) if summary else 0,
                "transcript_length": len(transcript) if transcript else 0
            }
        }), 200
        
    except Exception as e:
        logging.error(f"Raw Ingest Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
