import requests
import logging
import os

AUX_BASE_URL = "https://coachlink360.aux-rolplay.com/api"

def schedule_meeting(meeting_link, scheduled_time, title):
    """
    Schedules a meeting with the Aux API for transcript capture.
    Returns the meetingToken and meetingId on success.
    """
    url = f"{AUX_BASE_URL}/meetings/schedule"
    payload = {
        "meetingLink": meeting_link,
        "scheduled_time": scheduled_time, # Expected ISO format
        "title": title
    }
    
    try:
        logging.info(f"Aux API Request: POST {url} | Payload: {payload}")
        response = requests.post(url, json=payload, timeout=15)
        
        if response.status_code != 200:
            logging.error(f"Aux API Error: Status {response.status_code} | Body: {response.text}")
            return None
            
        data = response.json()
        if data.get("success"):
            logging.info(f"Aux API Success: ID={data.get('meetingId')} Token={data.get('meetingToken')}")
            return {
                "meetingId": data.get("meetingId"),
                "token": data.get("meetingToken")
            }
        else:
            logging.error(f"Aux API Success=False | Body: {data}")
            return None
    except Exception as e:
        logging.error(f"Aux API Exception: {e}")
        return None

def get_meeting_status(token):
    """
    Polls the Aux API for the status and transcript of a scheduled meeting.
    """
    url = f"{AUX_BASE_URL}/meetings/schedule/{token}"
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("success"):
            return data.get("meeting")
        return None
    except Exception as e:
        logging.error(f"Aux Status Error: {e}")
        return None
def trigger_survey_webhook(meeting_data):
    """
    Triggers the external webhook to send a survey link to the client/organizer.
    This replaces the Read.ai email flow.
    """
    url = f"https://projects.aux-rolplay.com/coachlink360/api/webhook"
    
    try:
        logging.info(f"Triggering survey webhook for meeting {meeting_data.get('meeting_id')}")
        response = requests.post(url, json=meeting_data, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logging.error(f"Survey Webhook Trigger Error: {e}")
        return None
