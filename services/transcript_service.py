import requests
import logging
import re
from database import db

def fetch_transcript(url: str) -> str:
    """
    Fetches transcript content from a URL.
    """
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.text
    except Exception as e:
        logging.error(f"Failed to fetch transcript from {url}: {e}")
        raise

def parse_transcript(content: str) -> list:
    """
    Parses transcript text into structural lines:
    [{'timestamp': '...', 'speaker': '...', 'text': '...'}]
    
    Supports:
    - WebVTT (simple)
    - [Time] Speaker: Text
    - Speaker: Text
    """
    lines = []
    
    # Pre-processing (remove VTT header if present)
    if content.startswith("WEBVTT"):
        content = re.sub(r'WEBVTT.*\n', '', content)

    # Split by lines
    raw_lines = content.splitlines()
    
    current_speaker = "Unknown"
    current_time = ""
    
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
            
        # Regex to find [00:00] or 00:00
        time_match = re.search(r'\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?', line)
        if time_match:
            current_time = time_match.group(1)
            # Remove time from line to find speaker
            line = line.replace(time_match.group(0), "").strip()
            
        # Regex to find Speaker:
        speaker_match = re.search(r'^([^:]+):\s*(.*)', line)
        if speaker_match:
            current_speaker = speaker_match.group(1).strip()
            text = speaker_match.group(2).strip()
            
            lines.append({
                "timestamp": current_time,
                "speaker": current_speaker,
                "text": text
            })
        else:
            # Continuation of previous line or just text
            if lines and lines[-1]['speaker'] == current_speaker:
                 lines[-1]['text'] += " " + line
            else:
                lines.append({
                    "timestamp": current_time,
                    "speaker": current_speaker,
                    "text": line
                })
                
    return lines

def store_transcript(meeting_id: int, parsed_lines: list, source: str = "read_ai"):
    """
    Stores parsed transcript lines in the DB.
    """
    if not parsed_lines:
        return

    # Bulk insert
    conn = db.get_connection()
    cur = conn.cursor()
    
    try:
        query = "INSERT INTO meeting_transcripts (meeting_id, speaker, timestamp, text, source) VALUES (?, ?, ?, ?, ?)"
        data = [(meeting_id, l['speaker'], l['timestamp'], l['text'], source) for l in parsed_lines]
        
        if db.is_postgres:
            query = query.replace('?', '%s')
            
        cur.executemany(query, data)
        conn.commit()
    except Exception as e:
        logging.error(f"Failed to store transcript: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

def get_full_transcript_text(parsed_lines: list) -> str:
    """Reconstructs full text for AI consumption."""
    return "\n".join([f"{l['speaker']}: {l['text']}" for l in parsed_lines])
