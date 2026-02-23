import requests
import logging
import os
import traceback
import json

AUX_BASE_URL = os.getenv("AUX_BASE_URL", "https://coachlink360.aux-rolplay.com/api")
AUX_FALLBACK_URL = os.getenv("AUX_FALLBACK_URL")

def schedule_meeting(meeting_link, scheduled_time, title, attendee_name="Rolplay (AI Coach)"):
    """
    Schedules a meeting with the Aux API for transcript capture.
    Tries primary URL, then fallback if configured.
    """
    url = f"{AUX_BASE_URL}/meetings/schedule"
    
    payload = {
        "meetingLink": meeting_link,
        "meeting_link": meeting_link,
        "scheduled_time": scheduled_time, 
        "scheduledTime": scheduled_time,
        "title": title,
        "attendee_name": attendee_name,
        "attendeeName": attendee_name
    }
    
    urls = [f"{AUX_BASE_URL}/meetings/schedule"]
    if AUX_FALLBACK_URL:
        urls.append(f"{AUX_FALLBACK_URL}/meetings/schedule")

    last_error = None
    for url in urls:
        logging.info("=" * 60)
        logging.info(f"[AUX API] Attempting schedule at: {url}")
        try:
            response = requests.post(url, json=payload, timeout=15)
            logging.info(f"[AUX API] Response Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    meeting_id = data.get('meetingId')
                    token = data.get('meetingToken')
                    logging.info(f"[AUX API] SUCCESS at {url}! meetingId={meeting_id}, token={token}")
                    return {"meetingId": meeting_id, "token": token}
                else:
                    logging.warning(f"[AUX API] API success=false at {url}: {data}")
            else:
                logging.warning(f"[AUX API] HTTP {response.status_code} at {url}: {response.text}")
        except Exception as e:
            logging.error(f"[AUX API] Failed at {url}: {e}")
            last_error = e
            
    logging.error(f"[AUX API] All scheduling attempts failed. Last error: {last_error}")
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
