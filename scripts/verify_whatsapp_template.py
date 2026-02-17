import os
import sys
import json
import traceback
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import db

def verify_template_direct():
    try:
        sid = os.getenv("TWILIO_TEMPLATE_SID")
        account = os.getenv("TWILIO_ACCOUNT_SID")
        token = os.getenv("TWILIO_AUTH_TOKEN")
        from_num = os.getenv("TWILIO_WHATSAPP_FROM")
        
        db.init_db()
        user = db.execute_query("SELECT name, phone FROM users LIMIT 1", fetch_one=True)
        to_number = user['phone'] if user else "+15555555555"

        # Ensure whatsapp: prefix
        if not to_number.startswith("whatsapp:"):
            to_number = f"whatsapp:{to_number}"

        print(f"Sending From: {from_num}")
        print(f"Sending To: {to_number}")

        vars = {
            "1": "Test",
            "2": "Verification",
            "3": "Check",
            "4": "Done"
        }
        
        vars_json = json.dumps(vars)
        
        client = Client(account, token)
        msg = client.messages.create(
            from_=from_num,
            content_sid=sid,
            content_variables=vars_json,
            to=to_number
        )
        print(f"SUCCESS: {msg.sid}")
        
    except Exception as e:
        with open("error_log.txt", "w") as f:
            f.write(str(e))
            f.write("\n\n")
            f.write(traceback.format_exc())
            f.write(f"\n\nCode: {getattr(e, 'code', 'N/A')}")
            f.write(f"\nMsg: {getattr(e, 'msg', 'N/A')}")

if __name__ == "__main__":
    verify_template_direct()
