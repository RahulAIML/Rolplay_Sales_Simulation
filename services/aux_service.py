import requests
import logging
import os
import traceback

AUX_BASE_URL = "https://coachlink360.aux-rolplay.com/api"

def schedule_meeting(meeting_link, scheduled_time, title, attendee_name="Rolplay (AI Coach)"):
    """
    Schedules a meeting with the Aux API for transcript capture.
    Returns the meetingToken and meetingId on success.
    """
    url = f"{AUX_BASE_URL}/meetings/schedule"
    payload = {
        "meetingLink": meeting_link,
        "scheduled_time": scheduled_time, # Expected ISO format
        "title": title,
        "attendee_name": attendee_name
    }
    
    logging.info("=" * 60)
    logging.info(f"[AUX API] schedule_meeting() called")
    logging.info(f"[AUX API] URL: {url}")
    logging.info(f"[AUX API] Payload: {payload}")
    
    try:
        logging.info(f"[AUX API] Sending POST request...")
        response = requests.post(url, json=payload, timeout=15)
        
        logging.info(f"[AUX API] Response Status: {response.status_code}")
        logging.info(f"[AUX API] Response Headers: {dict(response.headers)}")
        
        if response.status_code != 200:
            logging.error(f"[AUX API] ERROR: Status {response.status_code}")
            logging.error(f"[AUX API] Response Body: {response.text}")
            return None
            
        data = response.json()
        logging.info(f"[AUX API] Response Data: {data}")
        
        if data.get("success"):
            meeting_id = data.get('meetingId')
            token = data.get('meetingToken')
            provider = data.get('provider', 'unknown')
            logging.info(f"[AUX API] SUCCESS! meetingId={meeting_id}, token={token}, provider={provider}")
            return {
                "meetingId": meeting_id,
                "token": token
            }
        else:
            logging.error(f"[AUX API] ERROR: API returned success=false")
            logging.error(f"[AUX API] Full response: {data}")
            return None
    except requests.exceptions.Timeout:
        logging.error(f"[AUX API] ERROR: Request timeout after 15s")
        return None
    except requests.exceptions.RequestException as e:
        logging.error(f"[AUX API] ERROR: Request failed - {e}")
        return None
    except Exception as e:
        logging.error(f"[AUX API] ERROR: Unexpected exception - {e}")
        logging.error(f"[AUX API] Traceback: {traceback.format_exc()}")
        return None

def get_meeting_status(token):
    """
    Polls the Aux API for the status and transcript of a scheduled meeting.
    """
    url = f"{AUX_BASE_URL}/meetings/schedule/{token}"
    
    logging.info(f"[AUX API] get_meeting_status() called with token: {token[:20]}...")
    logging.info(f"[AUX API] URL: {url}")
    
    try:
        response = requests.get(url, timeout=10)
        logging.info(f"[AUX API] Status check response code: {response.status_code}")
        
        response.raise_for_status()
        data = response.json()
        logging.info(f"[AUX API] Status response data: {data}")
        
        if data.get("success"):
            meeting_data = data.get("meeting", {})
            status = meeting_data.get("status")
            attendee_state = meeting_data.get("attendee_bot_state")
            has_recording = bool(meeting_data.get("recording_url"))
            has_transcript = bool(meeting_data.get("transcript", {}).get("content"))
            
            logging.info(f"[AUX API] Meeting status: {status}, bot_state: {attendee_state}, has_recording: {has_recording}, has_transcript: {has_transcript}")
            return meeting_data
        else:
            logging.warning(f"[AUX API] Status check returned success=false: {data}")
            return None
    except requests.exceptions.Timeout:
        logging.error(f"[AUX API] ERROR: Status check timeout")
        return None
    except requests.exceptions.RequestException as e:
        logging.error(f"[AUX API] ERROR: Status check request failed - {e}")
        return None
    except Exception as e:
        logging.error(f"[AUX API] ERROR: Status check exception - {e}")
        logging.error(f"[AUX API] Traceback: {traceback.format_exc()}")
        return None
def trigger_survey_webhook(meeting_data):
    """
    Triggers the external webhook to send a survey link to the client/organizer.
    This replaces the Read.ai email flow.
    """
    url = f"https://projects.aux-rolplay.com/coachlink360/api/webhook"
    
    logging.info(f"[SURVEY WEBHOOK] trigger_survey_webhook() called")
    logging.info(f"[SURVEY WEBHOOK] URL: {url}")
    logging.info(f"[SURVEY WEBHOOK] Payload: {meeting_data}")
    
    try:
        response = requests.post(url, json=meeting_data, timeout=10)
        logging.info(f"[SURVEY WEBHOOK] Response status: {response.status_code}")
        response.raise_for_status()
        result = response.json()
        logging.info(f"[SURVEY WEBHOOK] Success: {result}")
        return result
    except requests.exceptions.Timeout:
        logging.error(f"[SURVEY WEBHOOK] ERROR: Timeout after 10s")
        return None
    except requests.exceptions.RequestException as e:
        logging.error(f"[SURVEY WEBHOOK] ERROR: Request failed - {e}")
        return None
    except Exception as e:
        logging.error(f"[SURVEY WEBHOOK] ERROR: Exception - {e}")
        logging.error(f"[SURVEY WEBHOOK] Traceback: {traceback.format_exc()}")
        return None
