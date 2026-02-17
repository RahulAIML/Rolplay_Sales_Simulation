import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import db

if __name__ == "__main__":
    db.init_db()
    # Update all users to this phone number for testing purposes
    phone = "+918927349484"
    print(f"Updating users to phone: {phone}")
    db.execute_query("UPDATE users SET phone = ?", (phone,), commit=True)
    
    # Verify
    users = db.execute_query("SELECT * FROM users", fetch_all=True)
    for u in users:
        print(f"User: {u['name']} -> {u['phone']}")
