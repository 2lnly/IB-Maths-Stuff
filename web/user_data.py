"""User data management - history and saved questions."""

import sqlite3
import os
from pathlib import Path
from datetime import datetime

# Use persistent storage on Render, fallback to local for development
DB_PATH = Path(os.environ.get('DB_PATH', '/data')) / 'users.db'
if not DB_PATH.parent.exists():
    DB_PATH = Path(__file__).parent / 'users.db'

def init_user_data_tables():
    """Initialize tables for user history and saved questions."""
    # Ensure the directory exists
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        cursor = conn.cursor()

        # Question history table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS question_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                question_id TEXT NOT NULL,
                subject TEXT NOT NULL,
                viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(user_id, question_id, subject)
            )
        ''')

        # Saved questions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS saved_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                question_id TEXT NOT NULL,
                subject TEXT NOT NULL,
                notes TEXT,
                saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(user_id, question_id, subject)
            )
        ''')

        conn.commit()
    finally:
        conn.close()


def get_user_id(username):
    """Get user ID from username."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
        result = cursor.fetchone()
        return result[0] if result else None
    finally:
        conn.close()


def track_question_view(username, question_id, subject):
    """Track that a user viewed a question. Updates timestamp if already viewed."""
    user_id = get_user_id(username)
    if not user_id:
        return False, "User not found"

    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO question_history (user_id, question_id, subject, viewed_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, question_id, subject)
            DO UPDATE SET viewed_at = ?
        ''', (user_id, question_id, subject, datetime.now(), datetime.now()))
        conn.commit()
        return True, "View tracked"
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()


def save_question(username, question_id, subject, notes=None):
    """Save a question for the user."""
    user_id = get_user_id(username)
    if not user_id:
        return False, "User not found"

    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO saved_questions (user_id, question_id, subject, notes)
            VALUES (?, ?, ?, ?)
        ''', (user_id, question_id, subject, notes))
        conn.commit()
        return True, "Question saved"
    except sqlite3.IntegrityError:
        return False, "Question already saved"
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()


def unsave_question(username, question_id, subject):
    """Remove a saved question."""
    user_id = get_user_id(username)
    if not user_id:
        return False, "User not found"

    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        cursor = conn.cursor()
        cursor.execute('''
            DELETE FROM saved_questions
            WHERE user_id = ? AND question_id = ? AND subject = ?
        ''', (user_id, question_id, subject))
        conn.commit()
        return True, "Question unsaved"
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()


def is_question_saved(username, question_id, subject):
    """Check if a question is saved by the user."""
    user_id = get_user_id(username)
    if not user_id:
        return False

    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id FROM saved_questions
            WHERE user_id = ? AND question_id = ? AND subject = ?
        ''', (user_id, question_id, subject))
        return cursor.fetchone() is not None
    finally:
        conn.close()


def get_user_history(username, subject=None, limit=50):
    """Get user's question history, optionally filtered by subject."""
    user_id = get_user_id(username)
    if not user_id:
        return []

    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        cursor = conn.cursor()
        if subject:
            cursor.execute('''
                SELECT question_id, subject, viewed_at
                FROM question_history
                WHERE user_id = ? AND subject = ?
                ORDER BY viewed_at DESC
                LIMIT ?
            ''', (user_id, subject, limit))
        else:
            cursor.execute('''
                SELECT question_id, subject, viewed_at
                FROM question_history
                WHERE user_id = ?
                ORDER BY viewed_at DESC
                LIMIT ?
            ''', (user_id, limit))

        results = cursor.fetchall()
        return [
            {
                'question_id': row[0],
                'subject': row[1],
                'viewed_at': row[2]
            }
            for row in results
        ]
    finally:
        conn.close()


def get_saved_questions(username, subject=None):
    """Get user's saved questions, optionally filtered by subject."""
    user_id = get_user_id(username)
    if not user_id:
        return []

    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        cursor = conn.cursor()
        if subject:
            cursor.execute('''
                SELECT question_id, subject, notes, saved_at
                FROM saved_questions
                WHERE user_id = ? AND subject = ?
                ORDER BY saved_at DESC
            ''', (user_id, subject))
        else:
            cursor.execute('''
                SELECT question_id, subject, notes, saved_at
                FROM saved_questions
                WHERE user_id = ?
                ORDER BY saved_at DESC
            ''', (user_id,))

        results = cursor.fetchall()
        return [
            {
                'question_id': row[0],
                'subject': row[1],
                'notes': row[2],
                'saved_at': row[3]
            }
            for row in results
        ]
    finally:
        conn.close()


def clear_all_user_data(username, subject=None):
    """Clear all history and saved questions for a user, optionally filtered by subject."""
    user_id = get_user_id(username)
    if not user_id:
        return False, "User not found"

    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        cursor = conn.cursor()
        if subject:
            # Clear only for specific subject
            cursor.execute('DELETE FROM question_history WHERE user_id = ? AND subject = ?', (user_id, subject))
            cursor.execute('DELETE FROM saved_questions WHERE user_id = ? AND subject = ?', (user_id, subject))
        else:
            # Clear all subjects
            cursor.execute('DELETE FROM question_history WHERE user_id = ?', (user_id,))
            cursor.execute('DELETE FROM saved_questions WHERE user_id = ?', (user_id,))
        conn.commit()
        return True, "All data cleared"
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()


# Initialize tables on import
init_user_data_tables()
