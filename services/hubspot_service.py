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

def sync_survey_response_to_contact(participant_email: str, survey_data: dict):
    """
    Syncs a survey response to HubSpot as a note on the participant's contact.
    
    Args:
        participant_email: Email of the survey respondent
        survey_data: Dictionary containing:
            - punctuality (1-5)
            - listening_understanding (1-5)
            - knowledge_expertise (1-5)
            - clarity_answers (1-5)
            - overall_value (1-5)
            - most_valuable (optional text)
            - improvements (optional text)
            - meeting_title (optional)
            - session_id (optional)
            - participant_name (optional)
            - submitted_at (optional timestamp)
    
    Returns:
        bool: True if synced successfully, False otherwise
    """
    hubspot = get_client()
    if not hubspot:
        logging.warning("HubSpot client not initialized - skipping survey sync")
        return False
    
    try:
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
        
        # Build formatted note body
        meeting_title = survey_data.get('meeting_title', 'Meeting')
        session_id = survey_data.get('session_id', '')
        submitted_at = survey_data.get('submitted_at', datetime.now(pytz.utc).strftime('%Y-%m-%d %H:%M:%S UTC'))
        
        note_body = f"📊 **Meeting Survey Response**\n\n"
        note_body += f"**Meeting:** {meeting_title}\n"
        if session_id:
            note_body += f"**Session ID:** {session_id}\n"
        note_body += f"**Submitted:** {submitted_at}\n\n"
        
        note_body += "**RATINGS (1-5):**\n"
        note_body += f"⏰ Punctuality: {stars(survey_data.get('punctuality'))}\n"
        note_body += f"👂 Listening & Understanding: {stars(survey_data.get('listening_understanding'))}\n"
        note_body += f"🎓 Knowledge & Expertise: {stars(survey_data.get('knowledge_expertise'))}\n"
        note_body += f"💬 Clarity of Answers: {stars(survey_data.get('clarity_answers'))}\n"
        note_body += f"✨ Overall Value: {stars(survey_data.get('overall_value'))}\n\n"
        
        # Add text feedback if provided
        if survey_data.get('most_valuable') or survey_data.get('improvements'):
            note_body += "**FEEDBACK:**\n"
            if survey_data.get('most_valuable'):
                note_body += f"**Most Valuable:** {survey_data.get('most_valuable')}\n"
            if survey_data.get('improvements'):
                note_body += f"**Improvements:** {survey_data.get('improvements')}\n"
        
        # Create note in HubSpot
        properties = {
            "hs_timestamp": datetime.now(pytz.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
            "hs_note_body": note_body
        }
        batch_input = SimplePublicObjectInputForCreate(
            properties=properties,
            associations=[{
                "to": {"id": contact_id},
                "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 202}]
            }]
        )
        hubspot.crm.objects.notes.basic_api.create(simple_public_object_input_for_create=batch_input)
        logging.info(f"HubSpot: Survey response synced for contact {participant_email} (ID: {contact_id})")
        return True
        
    except Exception as e:
        logging.error(f"HubSpot Survey Sync Error: {e}")
        return False

def sync_note_to_contact(client_db_id: int, note_body: str):
    """
    Syncs a note to a HubSpot contact. 
    Tries to use existing hubspot_contact_id, or searches by email.
    """
    hubspot = get_client()
    if not hubspot:
        return

    try:
        # Get Client Data
        row = db.execute_query("SELECT email, hubspot_contact_id FROM clients WHERE id = ?", (client_db_id,), fetch_one=True)
        if not row:
            return

        email = row['email']
        hs_id = row['hubspot_contact_id']

        # Discovery: Find by Email if ID missing
        if not hs_id and email:
            hs_id = search_contact_by_email(email)
            if hs_id:
                # Cache ID
                db.execute_query("UPDATE clients SET hubspot_contact_id = ? WHERE id = ?", (hs_id, client_db_id), commit=True)

        # Sync Note
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
            hubspot.crm.objects.notes.basic_api.create(simple_public_object_input_for_create=batch_input)
            logging.info(f"HubSpot: Note synced for contact {hs_id}")

    except Exception as e:
        logging.error(f"HubSpot Sync Error: {e}")
