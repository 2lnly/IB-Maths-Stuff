"""Time tracking module for questions and daily usage."""

from datetime import date
from database import get_db_connection, execute_query, USE_POSTGRES


def get_user_id(username):
    """Get user ID from username."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        execute_query(cursor, 'SELECT id FROM users WHERE username = %s', (username,))
        result = cursor.fetchone()
        return result[0] if result else None


def update_question_time(username, question_id, subject, seconds):
    """Add time to a question's total tracked time."""
    user_id = get_user_id(username)
    if not user_id:
        return False, 'User not found'

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            if USE_POSTGRES:
                execute_query(cursor, '''
                    INSERT INTO question_time_tracking (user_id, question_id, subject, total_seconds)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id, question_id, subject)
                    DO UPDATE SET total_seconds = question_time_tracking.total_seconds + EXCLUDED.total_seconds
                ''', (user_id, question_id, subject, seconds))
            else:
                # SQLite: check if exists, then update or insert
                execute_query(cursor, '''
                    SELECT total_seconds FROM question_time_tracking
                    WHERE user_id = %s AND question_id = %s AND subject = %s
                ''', (user_id, question_id, subject))
                result = cursor.fetchone()

                if result:
                    new_total = result[0] + seconds
                    execute_query(cursor, '''
                        UPDATE question_time_tracking
                        SET total_seconds = %s
                        WHERE user_id = %s AND question_id = %s AND subject = %s
                    ''', (new_total, user_id, question_id, subject))
                else:
                    execute_query(cursor, '''
                        INSERT INTO question_time_tracking (user_id, question_id, subject, total_seconds)
                        VALUES (%s, %s, %s, %s)
                    ''', (user_id, question_id, subject, seconds))

            conn.commit()
        return True, 'Time updated'
    except Exception as e:
        return False, str(e)


def get_question_time(username, question_id, subject):
    """Get total time spent on a question."""
    user_id = get_user_id(username)
    if not user_id:
        return 0

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            execute_query(cursor, '''
                SELECT total_seconds FROM question_time_tracking
                WHERE user_id = %s AND question_id = %s AND subject = %s
            ''', (user_id, question_id, subject))
            result = cursor.fetchone()
            return result[0] if result else 0
    except Exception:
        return 0


def update_daily_time(username, seconds):
    """Add time to today's total tracked time."""
    user_id = get_user_id(username)
    if not user_id:
        return False, 'User not found'

    today = date.today()

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            if USE_POSTGRES:
                execute_query(cursor, '''
                    INSERT INTO daily_usage (user_id, date, total_seconds)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (user_id, date)
                    DO UPDATE SET total_seconds = daily_usage.total_seconds + EXCLUDED.total_seconds
                ''', (user_id, today, seconds))
            else:
                # SQLite: check if exists, then update or insert
                execute_query(cursor, '''
                    SELECT total_seconds FROM daily_usage
                    WHERE user_id = %s AND date = %s
                ''', (user_id, today))
                result = cursor.fetchone()

                if result:
                    new_total = result[0] + seconds
                    execute_query(cursor, '''
                        UPDATE daily_usage
                        SET total_seconds = %s
                        WHERE user_id = %s AND date = %s
                    ''', (new_total, user_id, today))
                else:
                    execute_query(cursor, '''
                        INSERT INTO daily_usage (user_id, date, total_seconds)
                        VALUES (%s, %s, %s)
                    ''', (user_id, today, seconds))

            conn.commit()
        return True, 'Daily time updated'
    except Exception as e:
        return False, str(e)


def get_daily_time(username):
    """Get total time spent today."""
    user_id = get_user_id(username)
    if not user_id:
        return 0

    today = date.today()

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            execute_query(cursor, '''
                SELECT total_seconds FROM daily_usage
                WHERE user_id = %s AND date = %s
            ''', (user_id, today))
            result = cursor.fetchone()
            return result[0] if result else 0
    except Exception:
        return 0
