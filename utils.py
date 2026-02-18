import logging
import os
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
    If the string is naive (no timezone info), it assumes the APP_TIMEZONE 
    (from .env, defaults to UTC).
    """
    # Get app-level default timezone or fallback to UTC
    # Standardize on UTC for internal logic
    default_tz_str = os.getenv("APP_TIMEZONE", "Asia/Kolkata") 
    try:
        default_tz = pytz.timezone(default_tz_str)
    except Exception:
        default_tz = pytz.utc

    try:
        if not date_str:
            raise ValueError("Empty date string")
        
        dt = parser.parse(date_str)
        if dt.tzinfo is None:
            # Localize naive string to the app default zone
            dt = default_tz.localize(dt)
        
        # Always return UTC for consistent internal comparison
        return dt.astimezone(pytz.utc)
    except Exception as e:
        logging.warning(f"Date Parse Error ({date_str}): {e}")
        return datetime.now(pytz.utc)

def get_current_utc_time() -> datetime:
    """Returns the current aware UTC time."""
    return datetime.now(pytz.utc)

def get_current_local_time() -> datetime:
    """Returns the current aware local time based on APP_TIMEZONE."""
    tz_str = os.getenv("APP_TIMEZONE", "Asia/Kolkata")
    try:
        tz = pytz.timezone(tz_str)
    except:
        tz = pytz.utc
    return datetime.now(tz)

def to_user_timezone(dt: datetime, tz_str: str) -> datetime:
    """
    Converts an aware UTC datetime to the given IANA timezone string.
    Falls back to UTC if tz_str is invalid or missing.
    Examples: 'Asia/Kolkata', 'America/New_York', 'Europe/London'
    """
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    if not tz_str or tz_str.strip() == "":
        tz_str = "UTC"
    try:
        tz = pytz.timezone(tz_str)
    except Exception:
        logging.warning(f"Unknown timezone '{tz_str}', falling back to UTC")
        tz = pytz.utc
    return dt.astimezone(tz)

def to_local_time(dt: datetime, tz_str: str = None) -> datetime:
    """
    Converts an aware datetime to a timezone.
    If tz_str is provided, uses that. Otherwise falls back to APP_TIMEZONE env var.
    This allows per-user timezone support while keeping backward compatibility.
    """
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    resolved_tz_str = tz_str or os.getenv("APP_TIMEZONE", "UTC")
    return to_user_timezone(dt, resolved_tz_str)
