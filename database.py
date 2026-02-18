import os
import sqlite3
import logging
from urllib.parse import urlparse

# Optional import for Postgres (only needed in Prod)
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None

class DBHandler:
    def __init__(self):
        self.db_url = os.getenv("DATABASE_URL")
        self.is_postgres = bool(self.db_url)
        if self.is_postgres and not psycopg2:
            logging.error("DATABASE_URL is set but psycopg2 is not installed!")

    def get_connection(self):
        """Returns a raw connection object and a cursor functionality wrapper."""
        if self.is_postgres:
            conn = psycopg2.connect(self.db_url, sslmode='require')
            # auto-commit is often easier for simple scripts, but Flask usually manages transactions.
            # We'll stick to manual commit to match SQLite behavior in app.py
            return conn
        else:
            conn = sqlite3.connect("coachlink.db", timeout=30.0)
            conn.row_factory = sqlite3.Row
            return conn

    def normalize_query(self, query):
        """Converts ? placeholders to %s if using Postgres."""
        if self.is_postgres:
            return query.replace('?', '%s')
        return query

    def execute_query(self, query, params=(), fetch_one=False, fetch_all=False, commit=False):
        """
        Executes a query safely handling DB differences.
        Returns:
            - None (for inserts/updates)
            - Row/Dict (if fetch_one=True)
            - List[Row/Dict] (if fetch_all=True)
        """
        conn = self.get_connection()
        try:
            query = self.normalize_query(query)
            
            if self.is_postgres:
                # Use RealDictCursor for dict-like access
                cur = conn.cursor(cursor_factory=RealDictCursor)
            else:
                cur = conn.cursor()

            cur.execute(query, params)
            
            result = None
            if fetch_one:
                result = cur.fetchone()
            elif fetch_all:
                result = cur.fetchall()

            if commit:
                conn.commit()
            
            return result
        except Exception as e:
            logging.error(f"DB Error: {e} | Query: {query}")
            if commit:
                conn.rollback()
            raise e
        finally:
            conn.close()

    def init_db(self):
        """Creates tables using syntax compatible with both DBs where possible."""
        # Note: We need separate Create Table statements because of types like AUTOINCREMENT vs SERIAL
        
        create_client_sql = ""
        create_msg_sql = ""
        create_mtg_sql = ""
        create_usr_sql = ""

        if self.is_postgres:
            # Postgres Syntax
            create_client_sql = """
                CREATE TABLE IF NOT EXISTS clients (
                    id SERIAL PRIMARY KEY,
                    hubspot_contact_id TEXT,
                    name TEXT,
                    email TEXT UNIQUE,
                    phone TEXT UNIQUE,
                    company TEXT
                );
            """
            create_msg_sql = """
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    client_id INTEGER REFERENCES clients(id),
                    direction TEXT,
                    message TEXT,
                    timestamp TEXT
                );
            """
            create_mtg_sql = """
                CREATE TABLE IF NOT EXISTS meetings (
                    id SERIAL PRIMARY KEY,
                    outlook_event_id TEXT,
                    start_time TEXT,
                    end_time TEXT,
                    client_id INTEGER REFERENCES clients(id),
                    status TEXT,
                    last_client_reply TEXT,
                    salesperson_phone TEXT,
                    summary TEXT,
                    read_ai_url TEXT,
                    location TEXT,
                    attendees TEXT,
                    aux_meeting_id INTEGER,
                    aux_meeting_token TEXT,
                    title TEXT
                );
            """
            create_usr_sql = """
                CREATE TABLE IF NOT EXISTS users (
                    email TEXT PRIMARY KEY,
                    name TEXT,
                    phone TEXT,
                    hubspot_contact_id TEXT,
                    timezone TEXT DEFAULT 'UTC'
                );
            """

            create_transcripts_sql = """
                CREATE TABLE IF NOT EXISTS meeting_transcripts (
                    id SERIAL PRIMARY KEY,
                    meeting_id INTEGER REFERENCES meetings(id),
                    speaker TEXT,
                    timestamp TEXT,
                    text TEXT,
                    source TEXT DEFAULT 'read_ai',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """

            create_coaching_sql = """
                CREATE TABLE IF NOT EXISTS meeting_coaching (
                  id SERIAL PRIMARY KEY,
                  session_id TEXT UNIQUE NOT NULL,
                  title TEXT,
                  transcript TEXT NOT NULL,
                  source TEXT,
                  coaching JSONB,
                  summary TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """
            
            create_synced_surveys_sql = """
                CREATE TABLE IF NOT EXISTS synced_surveys (
                  id SERIAL PRIMARY KEY,
                  survey_id INTEGER UNIQUE NOT NULL,
                  participant_email TEXT,
                  synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """
        else:
            # SQLite Syntax
            create_client_sql = """
                CREATE TABLE IF NOT EXISTS clients (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hubspot_contact_id TEXT,
                    name TEXT,
                    email TEXT UNIQUE,
                    phone TEXT UNIQUE,
                    company TEXT
                );
            """
            create_msg_sql = """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id INTEGER,
                    direction TEXT,
                    message TEXT,
                    timestamp TEXT,
                    FOREIGN KEY(client_id) REFERENCES clients(id)
                );
            """
            create_mtg_sql = """
                CREATE TABLE IF NOT EXISTS meetings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    outlook_event_id TEXT,
                    start_time TEXT,
                    end_time TEXT,
                    client_id INTEGER,
                    status TEXT,
                    last_client_reply TEXT,
                    salesperson_phone TEXT,
                    summary TEXT,
                    read_ai_url TEXT,
                    location TEXT,
                    attendees TEXT,
                    aux_meeting_id INTEGER,
                    aux_meeting_token TEXT,
                    title TEXT,
                    FOREIGN KEY(client_id) REFERENCES clients(id)
                );
            """
            create_usr_sql = """
                CREATE TABLE IF NOT EXISTS users (
                    email TEXT PRIMARY KEY,
                    name TEXT,
                    phone TEXT,
                    hubspot_contact_id TEXT,
                    timezone TEXT DEFAULT 'UTC'
                );
            """

            create_transcripts_sql = """
                CREATE TABLE IF NOT EXISTS meeting_transcripts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    meeting_id INTEGER,
                    speaker TEXT,
                    timestamp TEXT,
                    text TEXT,
                    source TEXT DEFAULT 'read_ai',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(meeting_id) REFERENCES meetings(id)
                );
            """

            create_coaching_sql = """
                CREATE TABLE IF NOT EXISTS meeting_coaching (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT UNIQUE NOT NULL,
                    title TEXT,
                    transcript TEXT NOT NULL,
                    source TEXT,
                    coaching TEXT,
                    summary TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """
            
            create_synced_surveys_sql = """
                CREATE TABLE IF NOT EXISTS synced_surveys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    survey_id INTEGER UNIQUE NOT NULL,
                    participant_email TEXT,
                    synced_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """

        # Execute
        # We can't use the execute_query helper easily for DDL scripts with multiple statements or specific logic
        # so we do a raw connection here.
        conn = self.get_connection()
        cur = conn.cursor()
        try:
            cur.execute(create_client_sql)
            cur.execute(create_msg_sql)
            cur.execute(create_mtg_sql)
            cur.execute(create_usr_sql)
            if 'create_transcripts_sql' in locals():
                cur.execute(create_transcripts_sql)
            if 'create_coaching_sql' in locals():
                cur.execute(create_coaching_sql)
            if 'create_synced_surveys_sql' in locals():
                cur.execute(create_synced_surveys_sql)
            conn.commit()
            
            # Migration check (Add columns if missing) - Simplified for robustness
            # In a real production app, we would use Alembic. 
            # Here we just blindly try to add columns and ignore "exists" errors for backward comp.
            try:
                # Add columns that might be missing from older schema versions
                alter_cmds = []
                if self.is_postgres:
                    alter_cmds = [
                        "ALTER TABLE clients ADD COLUMN IF NOT EXISTS hubspot_contact_id TEXT",
                        "ALTER TABLE users ADD COLUMN IF NOT EXISTS hubspot_contact_id TEXT",
                        "ALTER TABLE users ADD COLUMN IF NOT EXISTS timezone TEXT DEFAULT 'UTC'",
                        "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS last_client_reply TEXT",
                        "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS salesperson_phone TEXT",
                        "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS summary TEXT",
                        "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS read_ai_url TEXT",
                        "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS location TEXT",
                        "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS attendees TEXT",
                        "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS aux_meeting_id INTEGER",
                        "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS aux_meeting_token TEXT",
                        "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS title TEXT"
                    ]
                else:
                    # SQLite doesn't support IF NOT EXISTS in ALTER COLUMN easily, 
                    # relying on exception handling in app.py's original logic was smart.
                    # We will replicate strict checks.
                    
                    # Clients
                    cur.execute("PRAGMA table_info(clients)")
                    cols = [row['name'] for row in cur.fetchall()]
                    if 'hubspot_contact_id' not in cols:
                        cur.execute("ALTER TABLE clients ADD COLUMN hubspot_contact_id TEXT")
                    
                    # Meetings
                    cur.execute("PRAGMA table_info(meetings)")
                    cols = [row['name'] for row in cur.fetchall()]
                    if 'last_client_reply' not in cols:
                        cur.execute("ALTER TABLE meetings ADD COLUMN last_client_reply TEXT")
                    if 'salesperson_phone' not in cols:
                        cur.execute("ALTER TABLE meetings ADD COLUMN salesperson_phone TEXT")
                    if 'summary' not in cols:
                        cur.execute("ALTER TABLE meetings ADD COLUMN summary TEXT")
                    if 'read_ai_url' not in cols:
                        cur.execute("ALTER TABLE meetings ADD COLUMN read_ai_url TEXT")
                    if 'location' not in cols:
                        cur.execute("ALTER TABLE meetings ADD COLUMN location TEXT")
                    if 'attendees' not in cols:
                        cur.execute("ALTER TABLE meetings ADD COLUMN attendees TEXT")
                    if 'aux_meeting_id' not in cols:
                        cur.execute("ALTER TABLE meetings ADD COLUMN aux_meeting_id INTEGER")
                    if 'aux_meeting_token' not in cols:
                        cur.execute("ALTER TABLE meetings ADD COLUMN aux_meeting_token TEXT")
                    if 'title' not in cols:
                        cur.execute("ALTER TABLE meetings ADD COLUMN title TEXT")

                    # Users
                    cur.execute("PRAGMA table_info(users)")
                    cols = [row['name'] for row in cur.fetchall()]
                    if 'hubspot_contact_id' not in cols:
                        cur.execute("ALTER TABLE users ADD COLUMN hubspot_contact_id TEXT")
                    if 'timezone' not in cols:
                        cur.execute("ALTER TABLE users ADD COLUMN timezone TEXT DEFAULT 'UTC'")

                    # Transcripts
                    cur.execute("PRAGMA table_info(meeting_transcripts)")
                    cols = [row['name'] for row in cur.fetchall()]
                    if 'source' not in cols:
                         cur.execute("ALTER TABLE meeting_transcripts ADD COLUMN source TEXT DEFAULT 'read_ai'")
                    if 'created_at' not in cols:
                         cur.execute("ALTER TABLE meeting_transcripts ADD COLUMN created_at TEXT DEFAULT CURRENT_TIMESTAMP")
                        
                for cmd in alter_cmds:
                    cur.execute(cmd)
                
                # Add summary column to meeting_coaching
                self._add_summary_column_to_coaching(cur)
                
                conn.commit()
                
            except Exception as e:
                logging.warning(f"Schema migration warning: {e}")
                
        except Exception as e:
            logging.error(f"Init DB Error: {e}")
        finally:
            conn.close()

    def _add_summary_column_to_coaching(self, cur):
        """Helper to safely add summary column to meeting_coaching if missing."""
        try:
            if self.is_postgres:
                cur.execute("ALTER TABLE meeting_coaching ADD COLUMN IF NOT EXISTS summary TEXT")
            else:
                cur.execute("PRAGMA table_info(meeting_coaching)")
                cols = [row['name'] for row in cur.fetchall()]
                if 'summary' not in cols:
                     cur.execute("ALTER TABLE meeting_coaching ADD COLUMN summary TEXT")
        except Exception as e:
            logging.warning(f"Could not add summary column to meeting_coaching: {e}")

# Singleton shared instance
db = DBHandler()
