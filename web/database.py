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
    from psycopg2.extras import RealDictCursor
    # Fix Render's postgres:// URL to postgresql://
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

# SQLite path for local development
DB_PATH = Path(__file__).parent / 'users.db'

def convert_query(query):
    """Convert PostgreSQL %s placeholders to SQLite ? placeholders if needed."""
    if USE_POSTGRES:
        return query
    else:
        # Convert %s to ? for SQLite
        return query.replace('%s', '?')

@contextmanager
def get_db_connection():
    """Get a database connection (PostgreSQL in production, SQLite locally)."""
    if USE_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL)
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

def execute_query(cursor, query, params=None):
    """Execute a query with automatic placeholder conversion."""
    converted_query = convert_query(query)
    if params:
        cursor.execute(converted_query, params)
    else:
        cursor.execute(converted_query)

def init_database():
    """Initialize database tables for both SQLite and PostgreSQL."""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        if USE_POSTGRES:
            # PostgreSQL syntax
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL DEFAULT '1234',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

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

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS question_time_tracking (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    question_id TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    total_seconds INTEGER DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    UNIQUE(user_id, question_id, subject)
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS daily_usage (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    date DATE NOT NULL,
                    total_seconds INTEGER DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    UNIQUE(user_id, date)
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS global_chat (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            ''')

            cursor.execute('CREATE INDEX IF NOT EXISTS idx_chat_created ON global_chat(created_at DESC)')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS question_notes (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    question_id TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    note TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            ''')

            cursor.execute('CREATE INDEX IF NOT EXISTS idx_notes_question ON question_notes(question_id, subject)')
        else:
            # SQLite syntax
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL DEFAULT '1234',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS question_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    question_id TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    UNIQUE(user_id, question_id, subject)
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS saved_questions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    question_id TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    notes TEXT,
                    saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    UNIQUE(user_id, question_id, subject)
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS question_time_tracking (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    question_id TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    total_seconds INTEGER DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    UNIQUE(user_id, question_id, subject)
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS daily_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    date DATE NOT NULL,
                    total_seconds INTEGER DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    UNIQUE(user_id, date)
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS global_chat (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            ''')

            cursor.execute('CREATE INDEX IF NOT EXISTS idx_chat_created ON global_chat(created_at DESC)')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS question_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    question_id TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    note TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            ''')

            cursor.execute('CREATE INDEX IF NOT EXISTS idx_notes_question ON question_notes(question_id, subject)')

        conn.commit()

# Initialize database on import
init_database()
