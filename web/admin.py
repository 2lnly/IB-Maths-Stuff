"""Admin CLI tool for managing users and messages."""

import argparse
import sys
from datetime import datetime, timedelta
from database import get_db_connection, execute_query, USE_POSTGRES

# ANSI color codes for terminal output
class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def print_success(message):
    """Print success message in green."""
    print(f"{Colors.GREEN}✓{Colors.RESET} {message}")

def print_error(message):
    """Print error message in red."""
    print(f"{Colors.RED}✗{Colors.RESET} {message}")

def print_warning(message):
    """Print warning message in yellow."""
    print(f"{Colors.YELLOW}⚠{Colors.RESET} {message}")

def print_info(message):
    """Print info message in blue."""
    print(f"{Colors.BLUE}ℹ{Colors.RESET} {message}")

def confirm_action(message):
    """Ask user to confirm a destructive action."""
    response = input(f"{Colors.YELLOW}⚠ {message} (yes/no): {Colors.RESET}")
    return response.lower() in ['yes', 'y']

# ============ USER MANAGEMENT ============

def list_users(args):
    """List all users with their statistics."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            if USE_POSTGRES:
                execute_query(cursor, """
                    SELECT u.id, u.username, u.password, u.is_owner, u.created_at,
                           COUNT(DISTINCT gc.id) as message_count
                    FROM users u
                    LEFT JOIN global_chat gc ON u.id = gc.user_id
                    GROUP BY u.id, u.username, u.password, u.is_owner, u.created_at
                    ORDER BY u.created_at DESC
                """, None)
            else:
                execute_query(cursor, """
                    SELECT u.id, u.username, u.password, u.is_owner, u.created_at,
                           COUNT(DISTINCT gc.id) as message_count
                    FROM users u
                    LEFT JOIN global_chat gc ON u.id = gc.user_id
                    GROUP BY u.id, u.username, u.password, u.is_owner, u.created_at
                    ORDER BY u.created_at DESC
                """, None)

            users = cursor.fetchall()

            if not users:
                print_warning("No users found")
                return

            print(f"\n{Colors.BOLD}{'ID':<6} {'Username':<20} {'Password':<20} {'Owner':<8} {'Messages':<10} {'Joined':<20}{Colors.RESET}")
            print("=" * 90)

            for user in users:
                user_id = user[0]
                username = user[1]
                password = user[2]
                is_owner = user[3]
                created_at = user[4]
                message_count = user[5]

                owner_badge = f"{Colors.RED}[OWNER]{Colors.RESET}" if is_owner else ""
                print(f"{user_id:<6} {username:<20} {password:<20} {owner_badge:<20} {message_count:<10} {created_at}")

            print(f"\nTotal users: {len(users)}")

    except Exception as e:
        print_error(f"Failed to list users: {e}")
        sys.exit(1)

def delete_user(args):
    """Delete a user account and all associated data."""
    username = args.username.strip().lower()

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Check if user exists
            execute_query(cursor, 'SELECT id, username, is_owner FROM users WHERE username = %s', (username,))
            user = cursor.fetchone()

            if not user:
                print_error(f"User '{username}' not found")
                return

            user_id = user[0]
            is_owner = user[1] if not USE_POSTGRES else user[2]

            # Prevent deletion of owner accounts
            if is_owner:
                print_error(f"Cannot delete owner account '{username}' for safety reasons")
                print_info("If you really need to remove an owner, use SQL directly")
                return

            # Confirm deletion
            if not args.confirm:
                if not confirm_action(f"Delete user '{username}' and ALL associated data?"):
                    print_info("Deletion cancelled")
                    return

            # Get statistics before deletion
            execute_query(cursor, 'SELECT COUNT(*) FROM global_chat WHERE user_id = %s', (user_id,))
            message_count = cursor.fetchone()[0]

            execute_query(cursor, 'SELECT COUNT(*) FROM question_history WHERE user_id = %s', (user_id,))
            history_count = cursor.fetchone()[0]

            execute_query(cursor, 'SELECT COUNT(*) FROM saved_questions WHERE user_id = %s', (user_id,))
            saved_count = cursor.fetchone()[0]

            # Delete user (CASCADE will handle related data)
            execute_query(cursor, 'DELETE FROM users WHERE id = %s', (user_id,))
            conn.commit()

            print_success(f"Deleted user '{username}'")
            print_info(f"  - Removed {message_count} chat messages")
            print_info(f"  - Removed {history_count} history entries")
            print_info(f"  - Removed {saved_count} saved questions")

    except Exception as e:
        print_error(f"Failed to delete user: {e}")
        sys.exit(1)

# ============ MESSAGE MANAGEMENT ============

def delete_messages(args):
    """Delete chat messages based on filters."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Build query based on arguments
            if args.all:
                # Delete all messages
                if not args.confirm:
                    execute_query(cursor, 'SELECT COUNT(*) FROM global_chat', None)
                    count = cursor.fetchone()[0]
                    if not confirm_action(f"Delete ALL {count} chat messages?"):
                        print_info("Deletion cancelled")
                        return

                execute_query(cursor, 'DELETE FROM global_chat', None)
                conn.commit()
                print_success("Deleted all chat messages")

            elif args.username:
                # Delete messages from specific user
                username = args.username.strip().lower()

                # Get user_id
                execute_query(cursor, 'SELECT id FROM users WHERE username = %s', (username,))
                user = cursor.fetchone()

                if not user:
                    print_error(f"User '{username}' not found")
                    return

                user_id = user[0]

                if not args.confirm:
                    execute_query(cursor, 'SELECT COUNT(*) FROM global_chat WHERE user_id = %s', (user_id,))
                    count = cursor.fetchone()[0]
                    if not confirm_action(f"Delete {count} messages from user '{username}'?"):
                        print_info("Deletion cancelled")
                        return

                execute_query(cursor, 'DELETE FROM global_chat WHERE user_id = %s', (user_id,))
                conn.commit()
                print_success(f"Deleted messages from user '{username}'")

            elif args.message_id:
                # Delete specific message by ID
                execute_query(cursor, 'SELECT id FROM global_chat WHERE id = %s', (args.message_id,))
                if not cursor.fetchone():
                    print_error(f"Message with ID {args.message_id} not found")
                    return

                if not args.confirm:
                    if not confirm_action(f"Delete message with ID {args.message_id}?"):
                        print_info("Deletion cancelled")
                        return

                execute_query(cursor, 'DELETE FROM global_chat WHERE id = %s', (args.message_id,))
                conn.commit()
                print_success(f"Deleted message with ID {args.message_id}")

            elif args.older_than:
                # Delete messages older than X days
                days = args.older_than
                cutoff_date = datetime.now() - timedelta(days=days)

                if USE_POSTGRES:
                    execute_query(cursor,
                        'SELECT COUNT(*) FROM global_chat WHERE created_at < %s',
                        (cutoff_date,))
                else:
                    execute_query(cursor,
                        'SELECT COUNT(*) FROM global_chat WHERE created_at < ?',
                        (cutoff_date,))

                count = cursor.fetchone()[0]

                if count == 0:
                    print_info(f"No messages older than {days} days found")
                    return

                if not args.confirm:
                    if not confirm_action(f"Delete {count} messages older than {days} days?"):
                        print_info("Deletion cancelled")
                        return

                if USE_POSTGRES:
                    execute_query(cursor, 'DELETE FROM global_chat WHERE created_at < %s', (cutoff_date,))
                else:
                    execute_query(cursor, 'DELETE FROM global_chat WHERE created_at < ?', (cutoff_date,))

                conn.commit()
                print_success(f"Deleted {count} messages older than {days} days")

            else:
                print_error("No deletion criteria specified. Use --all, --username, --id, or --older-than")
                sys.exit(1)

    except Exception as e:
        print_error(f"Failed to delete messages: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

def list_messages(args):
    """List recent chat messages."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            limit = args.limit or 20

            execute_query(cursor, """
                SELECT gc.id, gc.username, gc.message, gc.created_at, u.is_owner
                FROM global_chat gc
                LEFT JOIN users u ON gc.user_id = u.id
                ORDER BY gc.created_at DESC
                LIMIT %s
            """, (limit,))

            messages = cursor.fetchall()

            if not messages:
                print_warning("No messages found")
                return

            print(f"\n{Colors.BOLD}Recent chat messages (limit: {limit}):{Colors.RESET}\n")

            for msg in reversed(messages):
                msg_id = msg[0]
                username = msg[1]
                message = msg[2]
                created_at = msg[3]
                is_owner = msg[4]

                owner_badge = f"{Colors.RED}[OWNER]{Colors.RESET}" if is_owner else ""
                print(f"{Colors.CYAN}#{msg_id}{Colors.RESET} {owner_badge}{Colors.BOLD}{username}{Colors.RESET} ({created_at}):")
                print(f"  {message}\n")

    except Exception as e:
        print_error(f"Failed to list messages: {e}")
        sys.exit(1)

# ============ MAIN CLI ============

def main():
    parser = argparse.ArgumentParser(
        description='Admin CLI tool for managing users and messages',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List all users
  python admin.py list-users

  # List recent messages
  python admin.py list-messages --limit 50

  # Delete all messages
  python admin.py delete-messages --all --confirm

  # Delete messages from specific user
  python admin.py delete-messages --username john_doe --confirm

  # Delete messages older than 7 days
  python admin.py delete-messages --older-than 7 --confirm

  # Delete specific message
  python admin.py delete-messages --id 123 --confirm

  # Delete user account
  python admin.py delete-user --username john_doe --confirm
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # list-users command
    list_users_parser = subparsers.add_parser('list-users', help='List all users with statistics')
    list_users_parser.set_defaults(func=list_users)

    # delete-user command
    delete_user_parser = subparsers.add_parser('delete-user', help='Delete a user account')
    delete_user_parser.add_argument('--username', required=True, help='Username to delete')
    delete_user_parser.add_argument('--confirm', action='store_true', help='Skip confirmation prompt')
    delete_user_parser.set_defaults(func=delete_user)

    # list-messages command
    list_messages_parser = subparsers.add_parser('list-messages', help='List recent chat messages')
    list_messages_parser.add_argument('--limit', type=int, default=20, help='Number of messages to show (default: 20)')
    list_messages_parser.set_defaults(func=list_messages)

    # delete-messages command
    delete_messages_parser = subparsers.add_parser('delete-messages', help='Delete chat messages')
    delete_group = delete_messages_parser.add_mutually_exclusive_group(required=True)
    delete_group.add_argument('--all', action='store_true', help='Delete all messages')
    delete_group.add_argument('--username', help='Delete messages from specific user')
    delete_group.add_argument('--id', dest='message_id', type=int, help='Delete specific message by ID')
    delete_group.add_argument('--older-than', type=int, help='Delete messages older than X days')
    delete_messages_parser.add_argument('--confirm', action='store_true', help='Skip confirmation prompt')
    delete_messages_parser.set_defaults(func=delete_messages)

    # Parse arguments
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Print header
    print(f"\n{Colors.BOLD}{'=' * 60}{Colors.RESET}")
    print(f"{Colors.BOLD}Admin CLI Tool{Colors.RESET}")
    print(f"{Colors.BOLD}{'=' * 60}{Colors.RESET}")
    print(f"Database: {Colors.CYAN}{'PostgreSQL' if USE_POSTGRES else 'SQLite'}{Colors.RESET}\n")

    # Execute command
    args.func(args)

    print()  # Empty line at the end

if __name__ == '__main__':
    main()
