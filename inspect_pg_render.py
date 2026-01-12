import psycopg2
import sys

# Connection URL provided
DB_URL = "postgresql://coachlink_user:tlegcNMZzPJJsMOfRI4wHKKA6SkgICU7@dpg-d59rd6chg0os73chg0kg-a.singapore-postgres.render.com/coachlink"

def inspect_db():
    try:
        print(f"Connecting to Render PostgreSQL...")
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        
        # Get all table names
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name;
        """)
        tables = cur.fetchall()
        
        if not tables:
            print("No tables found in 'public' schema.")
            conn.close()
            return

        print(f"\nFound {len(tables)} tables:")
        print("-" * 50)
        
        for table in tables:
            t_name = table[0]
            # Count rows
            cur.execute(f'SELECT COUNT(*) FROM "{t_name}"')
            count = cur.fetchone()[0]
            print(f"Table: {t_name:<20} | Rows: {count}")
            
            # Show columns
            cur.execute(f"""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = '{t_name}';
            """)
            cols = cur.fetchall()
            col_names = [c[0] for c in cols]
            print(f"  Columns: {', '.join(col_names)}")

            # Show sample data
            if count > 0:
                 print(f"  Sample Data (Limit 20):")
                 cur.execute(f'SELECT * FROM "{t_name}" LIMIT 20')
                 rows = cur.fetchall()
                 
                 # Prepare headers
                 headers = [desc[0] for desc in cur.description]
                 
                 for i, row in enumerate(rows):
                     print(f"    Row {i+1}:")
                     for col, val in zip(headers, row):
                         print(f"      {col:<20}: {val}")
                     print("")
            print("-" * 50)
            
        cur.close()
        conn.close()
        print("\nInspection complete.")
        
    except Exception as e:
        print(f"Connection/Query Error: {e}")
        print("Note: Ensure your IP is allowed in Render dashboard or the DB accepts external connections.")

if __name__ == "__main__":
    inspect_db()
