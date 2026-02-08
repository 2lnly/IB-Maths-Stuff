"""Simple username-based authentication system."""

from database import get_db_connection, execute_query

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

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            execute_query(cursor, 'INSERT INTO users (username, password) VALUES (%s, %s)', (username, password))
            return True, "Account created successfully"
    except Exception as e:
        error_msg = str(e).lower()
        if 'unique' in error_msg or 'duplicate' in error_msg:
            return False, "Username already taken"
        return False, f"Error creating account: {str(e)}"

def check_user(username, password):
    """Check if user exists with correct password. Returns True if valid."""
    if not username or not password:
        return False

    username = username.strip().lower()

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            execute_query(cursor, 'SELECT id FROM users WHERE username = %s AND password = %s', (username, password))
            result = cursor.fetchone()
            return result is not None
    except Exception:
        return False
