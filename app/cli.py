"""CLI administration tool for bootstrapping and managing administrator accounts."""

import argparse
import getpass
import sys

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.auth_service import AuthService


def cli_main() -> None:
    """CLI command to securely create the initial administrator or reset credentials."""
    parser = argparse.ArgumentParser(description="Travel Agency CRM - Admin Management")
    parser.add_argument("command", choices=["create-admin", "reset-password"], help="Administrative action to perform")
    parser.add_argument("--username", "-u", type=str, help="Administrator username")
    parser.add_argument("--password", "-p", type=str, help="Administrator password")
    parser.add_argument("--setup-secret", "-s", type=str, help="Setup secret authorization key")

    args = parser.parse_args()

    if args.command == "create-admin":
        with SessionLocal() as db:
            if AuthService.is_initialized(db):
                print("Error: Application is already initialized. Administrator account already exists.", file=sys.stderr)
                sys.exit(1)

            username = args.username
            if not username:
                username = input("Enter administrator username: ").strip()

            password = args.password
            if not password:
                password = getpass.getpass("Enter administrator password: ")
                confirm_password = getpass.getpass("Confirm administrator password: ")
                if password != confirm_password:
                    print("Error: Passwords do not match.", file=sys.stderr)
                    sys.exit(1)

            setup_secret = args.setup_secret
            if not setup_secret:
                setup_secret = getpass.getpass("Enter SETUP_SECRET key: ")

            try:
                user = AuthService.initialize_admin(
                    db=db,
                    username=username,
                    password=password,
                    setup_secret=setup_secret,
                )
                print(f"Success: Administrator user '{user.username}' created successfully (ID={user.id}).")
            except Exception as e:
                print(f"Error initializing administrator: {str(e)}", file=sys.stderr)
                sys.exit(1)

    elif args.command == "reset-password":
        with SessionLocal() as db:
            username = args.username
            if not username:
                username = input("Enter administrator username [admin]: ").strip() or "admin"

            password = args.password
            if not password:
                password = getpass.getpass("Enter new administrator password: ")
                confirm_password = getpass.getpass("Confirm new administrator password: ")
                if password != confirm_password:
                    print("Error: Passwords do not match.", file=sys.stderr)
                    sys.exit(1)

            setup_secret = args.setup_secret
            if not setup_secret:
                setup_secret = getpass.getpass("Enter SETUP_SECRET key: ")

            try:
                user = AuthService.reset_admin_password(
                    db=db,
                    username=username,
                    new_password=password,
                    setup_secret=setup_secret,
                )
                print(f"Success: Password for administrator '{user.username}' was reset successfully.")
            except Exception as e:
                print(f"Error resetting administrator password: {str(e)}", file=sys.stderr)
                sys.exit(1)


# Preserve backward-compatible function name alias
create_admin = cli_main

if __name__ == "__main__":
    cli_main()
