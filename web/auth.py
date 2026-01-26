"""Simple username-based authentication system."""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / 'users.db'

def init_db():
    """Initialize the database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def create_user(username):
    """Create a new user. Returns (success, message)."""
    if not username or len(username.strip()) == 0:
        return False, "Username cannot be empty"

    username = username.strip().lower()

    if len(username) < 3:
        return False, "Username must be at least 3 characters"

    if len(username) > 20:
        return False, "Username must be less than 20 characters"

    # Only allow alphanumeric and underscores
    if not username.replace('_', '').isalnum():
        return False, "Username can only contain letters, numbers, and underscores"

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('INSERT INTO users (username) VALUES (?)', (username,))
        conn.commit()
        conn.close()
        return True, "Account created successfully"
    except sqlite3.IntegrityError:
        return False, "Username already taken"
    except Exception as e:
        return False, f"Error creating account: {str(e)}"

def check_user(username):
    """Check if user exists. Returns True if exists."""
    if not username:
        return False

    username = username.strip().lower()

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
        result = cursor.fetchone()
        conn.close()
        return result is not None
    except Exception:
        return False

# Initialize database on import
init_db()
