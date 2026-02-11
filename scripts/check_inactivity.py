import sys
import os
import logging
from datetime import datetime, timedelta

# Add parent dir to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db
from services import whatsapp_service

logging.basicConfig(level=logging.INFO)

INACTIVITY_THRESHOLD_MINUTES = 10
NUDGE_MESSAGE = "👋 Hey! Just a friendly reminder to reply *Done* once you've completed the follow-up tasks from the meeting analysis."

def check_inactivity_and_nudge():
    """
    Checks for meetings where:
    1. A transcript was processed (meaning analysis was sent).
    2. The status is not 'completed'.
    3. It's been > 10 minutes since transcript creation.
    4. The user hasn't replied since the transcript.
    5. We haven't already nudged them since the transcript.
    """
    conn = db.get_connection()
    conn.row_factory = None # We want tuples or handle dicts manually if needed, but dict_factory is default in db.py
    
    # We'll use the db.execute_query helper for simplicity if possible, but complex joins might need raw sql
    # Let's try raw SQL for this complex logic
    
    try:
        cur = conn.cursor()
        
        # Find candidate meetings
        # We need: meeting_id, client_id, salesperson_phone, transcript_time
        # Logic: 
        # - Join meetings & transcripts
        # - Filter status != 'completed'
        # - Filter transcript created_at < NOW - 10 mins
        
        # Note: created_at in meeting_transcripts is TEXT (ISO) in SQLite/Postgres as per schema
        
        query = """
            SELECT 
                m.id, 
                m.client_id, 
                m.salesperson_phone, 
                MAX(t.created_at) as transcript_time
            FROM meetings m
            JOIN meeting_transcripts t ON m.id = t.meeting_id
            WHERE m.status != 'completed'
            GROUP BY m.id, m.client_id, m.salesperson_phone
        """
        
        cur.execute(query)
        candidates = cur.fetchall()
        
        # Parse logic in python for simplicity regarding timestamps and message checks
        now = datetime.now()
        
        for row in candidates:
            # Handle row format (tuple vs dict depending on db driver)
            if isinstance(row, tuple):
                 m_id, c_id, phone, t_time_str = row
            else:
                 m_id = row['id']
                 c_id = row['client_id']
                 phone = row['salesperson_phone']
                 t_time_str = row['transcript_time']

            if not t_time_str:
                continue

            try:
                # Handle potential subtle format diffs
                t_dt = datetime.fromisoformat(t_time_str)
            except ValueError:
                # Try simple format if ISO fails (e.g. space instead of T)
                try:
                    t_dt = datetime.strptime(t_time_str, "%Y-%m-%d %H:%M:%S")
                except:
                    continue

            # 1. Check Threshold
            if (now - t_dt) < timedelta(minutes=INACTIVITY_THRESHOLD_MINUTES):
                continue
                
            # 2. Check for User Reply since Transcript
            # Look for incoming messages from this client_id where timestamp > transcript_time
            reply_query = """
                SELECT id FROM messages 
                WHERE client_id = ? 
                AND direction = 'incoming'
                AND timestamp > ?
                LIMIT 1
            """
            
            # Use raw cursor for consistency
            if db.is_postgres:
                reply_query = reply_query.replace('?', '%s')
                
            cur.execute(reply_query, (c_id, t_time_str))
            if cur.fetchone():
                logging.info(f"Meeting {m_id}: User replied recently. No nudge needed.")
                continue

            # 3. Check if ALREADY Nudged since Transcript
            # Look for outgoing message with NUDGE text where timestamp > transcript_time
            nudge_query = """
                SELECT id FROM messages 
                WHERE client_id = ? 
                AND direction = 'outgoing'
                AND message = ?
                AND timestamp > ?
                LIMIT 1
            """
             
            if db.is_postgres:
                nudge_query = nudge_query.replace('?', '%s')

            cur.execute(nudge_query, (c_id, NUDGE_MESSAGE, t_time_str))
            if cur.fetchone():
                logging.info(f"Meeting {m_id}: Already nudged. Skipping.")
                continue
                
            # ACTION: SEND NUDGE
            logging.info(f"Meeting {m_id}: Inactivity detected > 10m. Sending Nudge to {phone}.")
            
            # Send (using plain text for conversational nudge)
            sid = whatsapp_service.send_whatsapp_message(phone, NUDGE_MESSAGE)
            
            if sid:
                # Log Nudge in DB so we don't send again
                log_query = """
                    INSERT INTO messages (client_id, direction, message, timestamp) 
                    VALUES (?, 'outgoing', ?, ?)
                """
                if db.is_postgres:
                    log_query = log_query.replace('?', '%s')
                    
                cur.execute(log_query, (c_id, NUDGE_MESSAGE, now.isoformat()))
                conn.commit()
                
    except Exception as e:
        logging.error(f"Inactivity Check Failed: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    check_inactivity_and_nudge()
