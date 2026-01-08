import os
import logging
from twilio.rest import Client

# Configuration
ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
FROM_NUMBER = os.getenv("TWILIO_WHATSAPP_FROM")

def send_whatsapp_message(to_number: str, body: str) -> str:
    """
    Sends a WhatsApp message using Twilio.
    Returns the Message SID on success, or None on failure.
    """
    if not ACCOUNT_SID or not AUTH_TOKEN or not FROM_NUMBER:
        logging.error("Twilio credentials missing. Cannot send message.")
        return None

    if not to_number:
        logging.warning("Attempted to send WhatsApp to empty number.")
        return None

    try:
        client = Client(ACCOUNT_SID, AUTH_TOKEN)
        msg = client.messages.create(
            from_=FROM_NUMBER,
            body=body,
            to=to_number
        )
        logging.info(f"WhatsApp sent to {to_number}: {msg.sid}")
        return msg.sid
    except Exception as e:
        logging.error(f"Twilio Send Error: {e}")
        return None
