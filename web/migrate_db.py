"""Add password column to existing users database."""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / 'users.db'

def migrate():
    """Add password column to users table if it doesn't exist."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Check if password column exists
    cursor.execute("PRAGMA table_info(users)")
    columns = [column[1] for column in cursor.fetchall()]

    if 'password' not in columns:
        print("Adding password column to users table...")
        cursor.execute("ALTER TABLE users ADD COLUMN password TEXT NOT NULL DEFAULT '1234'")
        conn.commit()
        print("✅ Password column added successfully!")
    else:
        print("Password column already exists.")

    conn.close()

if __name__ == "__main__":
    migrate()
