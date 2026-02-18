"""
Survey polling service - Fetches survey responses from CoachLink360 API
and syncs them to HubSpot.
"""
import logging
import requests
from datetime import datetime, timedelta
from services import hubspot_service
from database import db

SURVEY_API_URL = "https://projects.aux-rolplay.com/coachlink360/api/webhook"

def poll_and_sync_surveys():
    """
    Polls the survey API for new responses and syncs them to HubSpot.
    Tracks which surveys have been processed to avoid duplicates.
    """
    try:
        # Fetch recent survey responses (last 50)
        response = requests.get(
            SURVEY_API_URL,
            params={"limit": 50},
            timeout=10
        )
        
        if response.status_code != 200:
            logging.error(f"Survey API returned {response.status_code}: {response.text}")
            return
        
        data = response.json()
        results = data.get("results", [])
        
        if not results:
            logging.info("No survey responses found")
            return
        
        synced_count = 0
        skipped_count = 0
        
        for survey in results:
            survey_id = survey.get("id")
            participant_email = survey.get("participant_email")
            
            if not survey_id or not participant_email:
                logging.warning(f"Skipping survey with missing ID or email: {survey}")
                continue
            
            # Check if already synced
            existing = db.execute_query(
                "SELECT id FROM synced_surveys WHERE survey_id = ?",
                (survey_id,),
                fetch_one=True
            )
            
            if existing:
                skipped_count += 1
                continue
            
            # Prepare survey data for HubSpot
            survey_data = {
                "punctuality": survey.get("punctuality"),
                "listening_understanding": survey.get("listening_understanding"),
                "knowledge_expertise": survey.get("knowledge_expertise"),
                "clarity_answers": survey.get("clarity_answers"),
                "overall_value": survey.get("overall_value"),
                "most_valuable": survey.get("most_valuable", ""),
                "improvements": survey.get("improvements", ""),
                "participant_name": survey.get("participant_name"),
                "meeting_title": survey.get("meeting_title"),
                "session_id": survey.get("meeting_id"),  # Using meeting_id as session_id
                "submitted_at": survey.get("submitted_at")
            }
            
            # Sync to HubSpot
            success = hubspot_service.sync_survey_response_to_contact(
                participant_email,
                survey_data
            )
            
            if success:
                # Mark as synced
                db.execute_query(
                    "INSERT INTO synced_surveys (survey_id, participant_email, synced_at) VALUES (?, ?, ?)",
                    (survey_id, participant_email, datetime.utcnow().isoformat()),
                    commit=True
                )
                synced_count += 1
                logging.info(f"✅ Synced survey {survey_id} for {participant_email}")
            else:
                logging.warning(f"⚠️ Failed to sync survey {survey_id} for {participant_email}")
        
        logging.info(f"Survey sync complete: {synced_count} synced, {skipped_count} already processed")
        
    except Exception as e:
        logging.error(f"Survey polling error: {e}")

def cleanup_old_sync_records():
    """Clean up sync records older than 30 days to prevent table bloat"""
    try:
        cutoff_date = (datetime.utcnow() - timedelta(days=30)).isoformat()
        db.execute_query(
            "DELETE FROM synced_surveys WHERE synced_at < ?",
            (cutoff_date,),
            commit=True
        )
        logging.info("Cleaned up old survey sync records")
    except Exception as e:
        logging.error(f"Cleanup error: {e}")
