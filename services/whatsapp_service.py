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

    try:
        client = Client(ACCOUNT_SID, AUTH_TOKEN)
        
        # Template mode for business-initiated messages
        if use_template and template_vars:
            template_sid = os.getenv("TWILIO_TEMPLATE_SID")
            
            if template_sid:
                try:
                    msg = client.messages.create(
                        from_=FROM_NUMBER,
                        content_sid=template_sid,
                        content_variables=json.dumps(template_vars),
                        to=to_number
                    )
                    logging.info(f"WhatsApp template sent to {to_number}: {msg.sid}")
                    return msg.sid
                except Exception as template_error:
                    logging.warning(f"Template send failed: {template_error}. Falling back to plain text.")
                    # Fallback: reconstruct message from template vars
                    if body is None:
                        body = "\n\n".join([v for v in template_vars.values() if v])
            else:
                logging.warning("TWILIO_TEMPLATE_SID not set. Using plain text.")
                # Fallback to plain text
                if body is None:
                    body = "\n\n".join([v for v in template_vars.values() if v])
        
        # Plain text mode (default for conversational messages)
        if body:
            msg = client.messages.create(
                from_=FROM_NUMBER,
                body=body,
                to=to_number
            )
            logging.info(f"WhatsApp sent to {to_number}: {msg.sid}")
            return msg.sid
        else:
            logging.error("No message body or template provided.")
            return None
            
    except Exception as e:
        logging.error(f"Twilio Send Error: {e}")
        return None
