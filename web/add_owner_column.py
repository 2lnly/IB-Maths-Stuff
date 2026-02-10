"""Migration script to add is_owner column and create xiaohe owner account."""

from database import get_db_connection, execute_query, USE_POSTGRES
import sys

def add_owner_column():
    """Add is_owner column to users table if it doesn't exist."""
    print("Checking if is_owner column exists...")

    with get_db_connection() as conn:
        cursor = conn.cursor()

        if USE_POSTGRES:
            # Check if column exists in PostgreSQL
            execute_query(cursor, """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name='users' AND column_name='is_owner'
            """, None)

            if cursor.fetchone():
                print("✓ is_owner column already exists in PostgreSQL")
            else:
                print("Adding is_owner column to PostgreSQL...")
                execute_query(cursor, "ALTER TABLE users ADD COLUMN is_owner BOOLEAN DEFAULT FALSE", None)
                print("✓ is_owner column added to PostgreSQL")
        else:
            # For SQLite, check if column exists
            cursor.execute("PRAGMA table_info(users)")
            columns = [row[1] for row in cursor.fetchall()]

            if 'is_owner' in columns:
                print("✓ is_owner column already exists in SQLite")
            else:
                print("Adding is_owner column to SQLite...")
                execute_query(cursor, "ALTER TABLE users ADD COLUMN is_owner INTEGER DEFAULT 0", None)
                print("✓ is_owner column added to SQLite")

        conn.commit()

def create_xiaohe_account():
    """Create xiaohe account with owner status, or update existing account."""
    print("\nSetting up xiaohe owner account...")

    xiaohe_username = 'xiaohe'
    xiaohe_password = r'[]\[\\'

    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Check if xiaohe account exists
        execute_query(cursor, "SELECT id, is_owner FROM users WHERE username = %s", (xiaohe_username,))
        result = cursor.fetchone()

        if result:
            user_id = result[0]
            is_owner = result[1]

            if is_owner:
                print(f"✓ xiaohe account already exists with owner status")
            else:
                # Update existing account to owner
                if USE_POSTGRES:
                    execute_query(cursor,
                        "UPDATE users SET is_owner = TRUE, password = %s WHERE username = %s",
                        (xiaohe_password, xiaohe_username))
                else:
                    execute_query(cursor,
                        "UPDATE users SET is_owner = 1, password = %s WHERE username = %s",
                        (xiaohe_password, xiaohe_username))
                print(f"✓ Updated existing xiaohe account to owner status")
        else:
            # Create new xiaohe account
            if USE_POSTGRES:
                execute_query(cursor,
                    "INSERT INTO users (username, password, is_owner) VALUES (%s, %s, TRUE)",
                    (xiaohe_username, xiaohe_password))
            else:
                execute_query(cursor,
                    "INSERT INTO users (username, password, is_owner) VALUES (%s, %s, 1)",
                    (xiaohe_username, xiaohe_password))
            print(f"✓ Created new xiaohe account with owner status")

        conn.commit()

def main():
    """Run the migration."""
    print("=" * 60)
    print("Migration: Add is_owner column and create xiaohe account")
    print("=" * 60)
    print(f"Database type: {'PostgreSQL' if USE_POSTGRES else 'SQLite'}")
    print()

    try:
        add_owner_column()
        create_xiaohe_account()

        print("\n" + "=" * 60)
        print("✓ Migration completed successfully!")
        print("=" * 60)
        print("\nYou can now:")
        print("1. Log in as 'xiaohe' with password: []\\[\\")
        print("2. xiaohe will have [owner] badge in global chat")
        print("3. Use admin.py to manage users and messages")

    except Exception as e:
        print(f"\n✗ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
