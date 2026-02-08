"""Database abstraction layer - supports both SQLite (local) and PostgreSQL (production)."""

import os
import sqlite3
from pathlib import Path
from contextlib import contextmanager

# Check if running on Render (or any production environment with DATABASE_URL)
DATABASE_URL = os.environ.get('DATABASE_URL')
USE_POSTGRES = DATABASE_URL is not None

if USE_POSTGRES:
    import psycopg2
    from psycopg2.extras import DictCursor
    # Fix Render's postgres:// URL to postgresql://
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

# SQLite path for local development
DB_PATH = Path(__file__).parent / 'users.db'

@contextmanager
def get_db_connection():
    """Get a database connection (PostgreSQL in production, SQLite locally)."""
    if USE_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL)
        conn.cursor_factory = DictCursor
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

def init_database():
    """Initialize database tables for both SQLite and PostgreSQL."""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL DEFAULT '1234',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Question history table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS question_history (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                question_id TEXT NOT NULL,
                subject TEXT NOT NULL,
                viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE(user_id, question_id, subject)
            )
        ''')

        # Saved questions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS saved_questions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                question_id TEXT NOT NULL,
                subject TEXT NOT NULL,
                notes TEXT,
                saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE(user_id, question_id, subject)
            )
        ''')

        conn.commit()

def get_user_id(username):
    """Get user ID from username."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
        result = cursor.fetchone()
        return result[0] if result else None

# Initialize database on import
init_database()
