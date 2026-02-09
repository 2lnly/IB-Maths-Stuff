"""User data management - history and saved questions."""

from datetime import datetime
from database import get_db_connection, execute_query

def track_question_view(username, question_id, subject):
    """Track that a user viewed a question. Updates timestamp if already viewed."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Get user_id in the same connection
            execute_query(cursor, 'SELECT id FROM users WHERE username = %s', (username,))
            result = cursor.fetchone()
            if not result:
                return False, "User not found"
            user_id = result[0]

            # Track view
            execute_query(cursor, '''
                INSERT INTO question_history (user_id, question_id, subject, viewed_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT(user_id, question_id, subject)
                DO UPDATE SET viewed_at = EXCLUDED.viewed_at
            ''', (user_id, question_id, subject, datetime.now()))
            return True, "View tracked"
    except Exception as e:
        return False, str(e)

def save_question(username, question_id, subject, notes=None):
    """Save a question for the user."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Get user_id in the same connection
            execute_query(cursor, 'SELECT id FROM users WHERE username = %s', (username,))
            result = cursor.fetchone()
            if not result:
                return False, "User not found"
            user_id = result[0]

            # Save question
            execute_query(cursor, '''
                INSERT INTO saved_questions (user_id, question_id, subject, notes)
                VALUES (%s, %s, %s, %s)
            ''', (user_id, question_id, subject, notes))
            return True, "Question saved"
    except Exception as e:
        error_msg = str(e).lower()
        if 'unique' in error_msg or 'duplicate' in error_msg:
            return False, "Question already saved"
        return False, str(e)

def unsave_question(username, question_id, subject):
    """Remove a saved question."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Get user_id in the same connection
            execute_query(cursor, 'SELECT id FROM users WHERE username = %s', (username,))
            result = cursor.fetchone()
            if not result:
                return False, "User not found"
            user_id = result[0]

            # Delete saved question
            execute_query(cursor, '''
                DELETE FROM saved_questions
                WHERE user_id = %s AND question_id = %s AND subject = %s
            ''', (user_id, question_id, subject))
            return True, "Question unsaved"
    except Exception as e:
        return False, str(e)

def is_question_saved(username, question_id, subject):
    """Check if a question is saved by the user."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Get user_id in the same connection
            execute_query(cursor, 'SELECT id FROM users WHERE username = %s', (username,))
            result = cursor.fetchone()
            if not result:
                return False
            user_id = result[0]

            # Check if saved
            execute_query(cursor, '''
                SELECT id FROM saved_questions
                WHERE user_id = %s AND question_id = %s AND subject = %s
            ''', (user_id, question_id, subject))
            return cursor.fetchone() is not None
    except Exception:
        return False

def get_user_history(username, subject=None, limit=50):
    """Get user's question history, optionally filtered by subject."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Get user_id in the same connection
            execute_query(cursor, 'SELECT id FROM users WHERE username = %s', (username,))
            result = cursor.fetchone()
            if not result:
                return []
            user_id = result[0]

            # Get history
            if subject:
                execute_query(cursor, '''
                    SELECT question_id, subject, viewed_at
                    FROM question_history
                    WHERE user_id = %s AND subject = %s
                    ORDER BY viewed_at DESC
                    LIMIT %s
                ''', (user_id, subject, limit))
            else:
                execute_query(cursor, '''
                    SELECT question_id, subject, viewed_at
                    FROM question_history
                    WHERE user_id = %s
                    ORDER BY viewed_at DESC
                    LIMIT %s
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
    except Exception:
        return []

def get_saved_questions(username, subject=None):
    """Get user's saved questions, optionally filtered by subject."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Get user_id in the same connection
            execute_query(cursor, 'SELECT id FROM users WHERE username = %s', (username,))
            result = cursor.fetchone()
            if not result:
                return []
            user_id = result[0]

            # Get saved questions
            if subject:
                execute_query(cursor, '''
                    SELECT question_id, subject, notes, saved_at
                    FROM saved_questions
                    WHERE user_id = %s AND subject = %s
                    ORDER BY saved_at DESC
                ''', (user_id, subject))
            else:
                execute_query(cursor, '''
                    SELECT question_id, subject, notes, saved_at
                    FROM saved_questions
                    WHERE user_id = %s
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
    except Exception:
        return []

def clear_all_user_data(username, subject=None):
    """Clear all history and saved questions for a user, optionally filtered by subject."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Get user_id in the same connection
            execute_query(cursor, 'SELECT id FROM users WHERE username = %s', (username,))
            result = cursor.fetchone()
            if not result:
                return False, "User not found"
            user_id = result[0]

            # Clear data
            if subject:
                # Clear only for specific subject
                execute_query(cursor, 'DELETE FROM question_history WHERE user_id = %s AND subject = %s', (user_id, subject))
                execute_query(cursor, 'DELETE FROM saved_questions WHERE user_id = %s AND subject = %s', (user_id, subject))
            else:
                # Clear all subjects
                execute_query(cursor, 'DELETE FROM question_history WHERE user_id = %s', (user_id,))
                execute_query(cursor, 'DELETE FROM saved_questions WHERE user_id = %s', (user_id,))
            return True, "All data cleared"
    except Exception as e:
        return False, str(e)
