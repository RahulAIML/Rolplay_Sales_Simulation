import os
import logging
from flask import Flask, request, jsonify, Response
from dotenv import load_dotenv
from twilio.twiml.messaging_response import MessagingResponse

from database import db
from services import meeting_service, whatsapp_service
from utils import normalize_phone
import scheduler

# 1. Setup & Config
load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

app = Flask(__name__)

# Initialize DB & Scheduler
db.init_db()
scheduler.start_scheduler()

# 2. Routes

@app.route('/health', methods=['GET'])
def health():
    return "OK", 200

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
        
        # Upsert User
        existing = db.execute_query("SELECT email FROM users WHERE email = ?", (email,), fetch_one=True)
        if existing:
            db.execute_query("UPDATE users SET name = ?, phone = ? WHERE email = ?", (name, phone, email), commit=True)
        else:
            db.execute_query("INSERT INTO users (email, name, phone) VALUES (?, ?, ?)", (email, name, phone), commit=True)
        
        # Welcome Message
        msg = (f"🎉 Welcome {name}! You are registered.\n\n"
               "Invite 'rahulbhattacharyackt@gmail.com' to your meetings to receive coaching.")
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

@app.route('/whatsapp-webhook', methods=['POST'])
def whatsapp_webhook():
    sender = request.values.get('From', '')
    body = request.values.get('Body', '').strip()
    
    response_text = meeting_service.handle_incoming_message(sender, body)
    
    resp = MessagingResponse()
    resp.message(response_text)
    return Response(str(resp), mimetype="text/xml")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
