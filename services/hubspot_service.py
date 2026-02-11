import os
import logging
from datetime import datetime
import pytz
from hubspot import HubSpot
from hubspot.crm.objects import SimplePublicObjectInputForCreate
from hubspot.crm.contacts import PublicObjectSearchRequest

from database import db

ACCESS_TOKEN = os.getenv("HUBSPOT_ACCESS_TOKEN")

def get_client():
    if not ACCESS_TOKEN:
        return None
    try:
        return HubSpot(access_token=ACCESS_TOKEN)
    except Exception as e:
        logging.warning(f"HubSpot Init Error: {e}")
        return None

def search_contact_by_email(email: str):
    """
    Search for an existing HubSpot contact by email.
    Returns the HubSpot contact ID if found, otherwise None.
    """
    hubspot = get_client()
    if not hubspot or not email:
        return None
    
    try:
        search_req = PublicObjectSearchRequest(
            filter_groups=[{
                "filters": [{
                    "propertyName": "email",
                    "operator": "EQ",
                    "value": email
                }]
            }]
        )
        res = hubspot.crm.contacts.search_api.do_search(public_object_search_request=search_req)
        if res.results:
            contact_id = res.results[0].id
            logging.info(f"HubSpot: Found existing contact {email} -> ID {contact_id}")
            return contact_id
        return None
    except Exception as e:
        logging.error(f"HubSpot Search Error: {e}")
        return None

def create_or_find_contact(email: str, name: str, phone: str):
    """
    Create a new HubSpot contact or find existing one by email.
    Returns the HubSpot contact ID (existing or newly created), or None on failure.
    """
    hubspot = get_client()
    if not hubspot:
        logging.warning("HubSpot client not initialized - skipping contact creation")
        return None
    
    # First, search for existing contact
    existing_id = search_contact_by_email(email)
    if existing_id:
        return existing_id
    
    # Create new contact if not found
    try:
        # Parse name into first and last name
        name_parts = name.strip().split(maxsplit=1)
        firstname = name_parts[0] if name_parts else ""
        lastname = name_parts[1] if len(name_parts) > 1 else ""
        
        properties = {
            "email": email,
            "firstname": firstname,
            "lastname": lastname,
            "phone": phone
        }
        
        contact_input = SimplePublicObjectInputForCreate(properties=properties)
        result = hubspot.crm.contacts.basic_api.create(simple_public_object_input_for_create=contact_input)
        
        contact_id = result.id
        logging.info(f"HubSpot: Created new contact {email} -> ID {contact_id}")
        return contact_id
        
    except Exception as e:
        logging.error(f"HubSpot Contact Creation Error: {e}")
        return None

def _create_ticket(contact_id: str, subject: str, content: str, priority: str = "LOW"):
    """
    Helper to create a ticket and associate it with a contact.
    """
    hubspot = get_client()
    if not hubspot or not contact_id:
        return False
        
    try:
        properties = {
            "subject": subject,
            "content": content,
            "hs_pipeline_stage": "1", # Default stage
            "hs_pipeline": "0",       # Default pipeline
            "hs_ticket_priority": priority
        }
        
        batch_input = SimplePublicObjectInputForCreate(
            properties=properties,
            associations=[{
                "to": {"id": contact_id},
                "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 16}] # 16 is Ticket -> Contact
            }]
        )
        
        result = hubspot.crm.tickets.basic_api.create(simple_public_object_input_for_create=batch_input)
        logging.info(f"HubSpot: Ticket created (ID: {result.id}) for contact {contact_id}")
        return True
    except Exception as e:
        logging.error(f"HubSpot Ticket Creation Error: {e}")
        return False

def sync_survey_response_to_contact(participant_email: str, survey_data: dict):
    """
    Syncs a survey response to HubSpot as a TICKET associated with the participant's contact.
    """
    # Find or create contact
    contact_id = search_contact_by_email(participant_email)
    
    if not contact_id:
        # Optionally create contact if they don't exist
        participant_name = survey_data.get('participant_name', participant_email.split('@')[0])
        contact_id = create_or_find_contact(participant_email, participant_name, "")
        
    if not contact_id:
        logging.warning(f"Could not find or create HubSpot contact for {participant_email}")
        return False
    
    # Format star ratings
    def stars(rating):
        rating = int(rating) if rating else 0
        return "⭐" * rating + f" ({rating}/5)"
    
    # Build formatted ticket body
    meeting_title = survey_data.get('meeting_title', 'Meeting')
    session_id = survey_data.get('session_id', '')
    submitted_at = survey_data.get('submitted_at', datetime.now(pytz.utc).strftime('%Y-%m-%d %H:%M:%S UTC'))
    
    ticket_subject = f"Survey Response: {meeting_title}"
    
    ticket_content = f"📊 **Meeting Survey Response**\n"
    if session_id:
        ticket_content += f"**Session ID:** {session_id}\n"
    ticket_content += f"**Submitted:** {submitted_at}\n\n"
    
    ticket_content += "**RATINGS (1-5):**\n"
    ticket_content += f"⏰ Punctuality: {stars(survey_data.get('punctuality'))}\n"
    ticket_content += f"👂 Listening & Understanding: {stars(survey_data.get('listening_understanding'))}\n"
    ticket_content += f"🎓 Knowledge & Expertise: {stars(survey_data.get('knowledge_expertise'))}\n"
    ticket_content += f"💬 Clarity of Answers: {stars(survey_data.get('clarity_answers'))}\n"
    ticket_content += f"✨ Overall Value: {stars(survey_data.get('overall_value'))}\n\n"
    
    # Add text feedback if provided
    if survey_data.get('most_valuable') or survey_data.get('improvements'):
        ticket_content += "**FEEDBACK:**\n"
        if survey_data.get('most_valuable'):
            ticket_content += f"**Most Valuable:** {survey_data.get('most_valuable')}\n"
        if survey_data.get('improvements'):
            ticket_content += f"**Improvements:** {survey_data.get('improvements')}\n"
    
    return _create_ticket(contact_id, ticket_subject, ticket_content, priority="MEDIUM")

def sync_note_to_contact(client_db_id: int, note_body: str):
    """
    Syncs a meeting note to a HubSpot contact as a TICKET.
    """
    # Get Client Data
    row = db.execute_query("SELECT email, hubspot_contact_id, name FROM clients WHERE id = ?", (client_db_id,), fetch_one=True)
    if not row:
        return

    email = row['email']
    hs_id = row['hubspot_contact_id']

    # Discovery: Find by Email if ID missing
    if not hs_id and email:
        hs_id = search_contact_by_email(email)
        if hs_id:
            db.execute_query("UPDATE clients SET hubspot_contact_id = ? WHERE id = ?", (hs_id, client_db_id), commit=True)

    if hs_id:
        ticket_subject = f"Meeting Feedback: {row['name'] or 'Client'}"
        _create_ticket(hs_id, ticket_subject, note_body)

def sync_meeting_analysis(client_db_id: int, meeting_title: str, analysis: dict, transcript_url: str):
    """
    Syncs the Post-Meeting Analysis and Transcript URL to HubSpot as a Ticket.
    """
    # Get Client Data
    row = db.execute_query("SELECT email, hubspot_contact_id, name FROM clients WHERE id = ?", (client_db_id,), fetch_one=True)
    if not row:
        logging.warning(f"Analysis Sync: Client {client_db_id} not found in DB.")
        return

    email = row['email']
    hs_id = row['hubspot_contact_id']
    
    # Just in case ID is missing but we have Email
    if not hs_id and email:
        hs_id = create_or_find_contact(email, row['name'] or "Client", "")
        if hs_id:
             db.execute_query("UPDATE clients SET hubspot_contact_id = ? WHERE id = ?", (hs_id, client_db_id), commit=True)
    
    if not hs_id:
        logging.warning(f"Analysis Sync: No HubSpot ID for Client {client_db_id} ({email})")
        return

    # Format Analysis
    objections = "\n".join([f"- {o['quote']} (Context: {o.get('context','')})" for o in analysis.get('objections', [])])
    buying_signals = "\n".join([f"- {s}" for s in analysis.get('buying_signals', [])])
    risks = "\n".join([f"- {r}" for r in analysis.get('risks', [])])
    next_steps = "\n".join([f"- {n}" for n in analysis.get('follow_up_actions', [])])
    
    content = (
        f"🧠 **AI Meeting Analysis**\n\n"
        f"**Meeting**: {meeting_title}\n"
        f"**Transcript**: {transcript_url}\n\n"
        f"🛑 **Objections**:\n{objections if objections else 'None registered'}\n\n"
        f"📈 **Buying Signals**:\n{buying_signals if buying_signals else 'None registered'}\n\n"
        f"⚠️ **Risks**:\n{risks if risks else 'None registered'}\n\n"
        f"🚀 **Recommended Next Steps**:\n{next_steps if next_steps else 'None registered'}"
    )
    
    subject = f"Meeting Analysis: {meeting_title}"
    
    return _create_ticket(hs_id, subject, content, priority="HIGH")

def get_contact_details(contact_id: str):
    """
    Fetch specific properties for a contact to use in AI Context.
    """
    hubspot = get_client()
    if not hubspot or not contact_id:
        return None
        
    try:
        properties = [
            "jobtitle", 
            "mobilephone", 
            "lifecyclestage", 
            "notes_last_updated",
            "industry",
            "company",
            "total_revenue"
        ]
        
        contact = hubspot.crm.contacts.basic_api.get_by_id(
            contact_id=contact_id, 
            properties=properties
        )
        return contact.properties
    except Exception as e:
        logging.error(f"HubSpot Get Details Error: {e}")
        return None

