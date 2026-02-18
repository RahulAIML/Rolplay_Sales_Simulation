import os
# Updated signature to support templates (force push)
import logging
import json
from twilio.rest import Client

# Configuration
ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
FROM_NUMBER = os.getenv("TWILIO_WHATSAPP_FROM")

def send_whatsapp_message(to_number: str, body: str = None, use_template: bool = False, template_vars: dict = None) -> str:
    """
    Sends a WhatsApp message using Twilio.
    
    Args:
        to_number: WhatsApp number (e.g., whatsapp:+1234567890)
        body: Plain text message (for conversational/session messages)
        use_template: If True, use approved content template for business-initiated messages
        template_vars: Dict of variables for template (e.g., {"1": "value1", "2": "value2"})
    
    Returns:
        Message SID on success, or None on failure.
    
    Note: 
        - Use templates for business-initiated messages (pre-meeting, post-meeting)
        - Use plain body for session messages (replies, coaching chat within 24hrs)
    """
    if not ACCOUNT_SID or not AUTH_TOKEN or not FROM_NUMBER:
        logging.error("Twilio credentials missing. Cannot send message.")
        return None

    if not to_number:
        logging.warning("Attempted to send WhatsApp to empty number.")
        return None

    # Twilio requires 'whatsapp:' prefix for WhatsApp messages
    # Ensure they are present for both FROM and TO
    actual_from = FROM_NUMBER if FROM_NUMBER.startswith("whatsapp:") else f"whatsapp:{FROM_NUMBER}"
    actual_to = to_number if to_number.startswith("whatsapp:") else f"whatsapp:{to_number}"

    try:
        client = Client(ACCOUNT_SID, AUTH_TOKEN)
        
        # Template mode for business-initiated messages
        if use_template:
            template_sid = os.getenv("TWILIO_TEMPLATE_SID")
            
            if not template_sid:
                logging.error("TWILIO_TEMPLATE_SID not set. Template send requested but SID missing.")
                return None
            
            if not template_vars:
                logging.error("Template requested but template_vars are missing.")
                return None

            try:
                msg = client.messages.create(
                    from_=actual_from,
                    content_sid=template_sid,
                    content_variables=json.dumps(template_vars),
                    to=actual_to
                )
                logging.info(f"WhatsApp template sent to {actual_to}: {msg.sid}")
                return msg.sid
            except Exception as template_error:
                # CRITICAL: If template send fails, we DO NOT fall back to plain text body.
                # A business-initiated body message will trigger Twilio Error 63016.
                logging.error(f"Twilio Template Send FAILED: {template_error}")
                return None
        
        # Plain text mode (for conversational/session messages within 24hr window)
        if body:
            msg = client.messages.create(
                from_=actual_from,
                body=body,
                to=actual_to
            )
            logging.info(f"WhatsApp freeform sent to {actual_to}: {msg.sid}")
            return msg.sid
        else:
            logging.error("No message body provided for freeform message.")
            return None
            
    except Exception as e:
        logging.error(f"Twilio Send Error: {e}")
        return None
