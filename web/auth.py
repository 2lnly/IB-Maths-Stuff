"""Simple username-based authentication system."""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / 'users.db'

def init_db():
    """Initialize the database."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL DEFAULT '1234',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
    finally:
        conn.close()

def create_user(username, password):
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

    # Validate password (only 1234 or 4321 allowed)
    if password not in ['1234', '4321']:
        return False, "Invalid password"

    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        cursor = conn.cursor()
        cursor.execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, password))
        conn.commit()
        return True, "Account created successfully"
    except sqlite3.IntegrityError:
        return False, "Username already taken"
    except Exception as e:
        return False, f"Error creating account: {str(e)}"
    finally:
        if conn:
            conn.close()

def check_user(username, password):
    """Check if user exists with correct password. Returns True if valid."""
    if not username or not password:
        return False

    username = username.strip().lower()

    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM users WHERE username = ? AND password = ?', (username, password))
        result = cursor.fetchone()
        return result is not None
    except Exception:
        return False
    finally:
        if conn:
            conn.close()

# Initialize database on import
init_db()
