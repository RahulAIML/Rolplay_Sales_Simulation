import os
import logging
import pytz
from dateutil import parser
from datetime import datetime, timedelta

def normalize_phone(phone_number: str) -> str:
    """
    Normalizes phone numbers to the WhatsApp format.
    Removes spaces, dashes, parentheses.
    Ensures 'whatsapp:' prefix is present.
    """
    if not phone_number:
        return None
    
    clean = str(phone_number).replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
    if not clean.startswith("whatsapp:"):
        return f"whatsapp:{clean}"
    return clean

def parse_iso_datetime(date_str: str) -> datetime:
    """
    Parses an ISO date string into a timezone-aware datetime object (UTC).
    Returns current UTC time + 30m if parsing fails (fallback).
    """
    try:
        if not date_str:
            raise ValueError("Empty date string")
        
        dt = parser.parse(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=pytz.utc)
        return dt
    except Exception as e:
        logging.warning(f"Date Parse Error ({date_str}): {e}")
        # Fallback to now
        return datetime.now(pytz.utc)

def get_current_utc_time() -> datetime:
    return datetime.now(pytz.utc)
