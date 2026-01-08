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
                    hs_id = res.results[0].id
                    # Cache ID
                    db.execute_query("UPDATE clients SET hubspot_contact_id = ? WHERE id = ?", (hs_id, client_db_id), commit=True)
                    logging.info(f"HubSpot: Linked {email} to ID {hs_id}")
            except Exception as e:
                logging.error(f"HubSpot Search Failed: {e}")

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
