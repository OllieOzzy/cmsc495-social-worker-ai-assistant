"""Provision accounts locally without exposing a public registration endpoint."""

import argparse
import os
import sqlite3
import sys
from getpass import getpass
from pathlib import Path

from pwdlib.exceptions import HashGenerationError

from documentation_assistant.backend.auth.passwords import (
    hash_password,
    validate_new_password,
)
from documentation_assistant.backend.db.connection import initialize_database
from documentation_assistant.backend.db.users import (
    DuplicateUsername,
    create_user,
    get_user_by_username,
)

# Public capstone credentials are enabled only by the explicit demo setup command.
_DEMO_PASSWORD = "password1234"  # nosec B105
_DEMO_ACCOUNTS = (
    ("admin", "Demo Administrator", "admin"),
    ("user", "Demo User", "user"),
)


def configure_account_commands(parser: argparse.ArgumentParser) -> None:
    """Add account commands while keeping the launcher's no-argument behavior."""
    commands = parser.add_subparsers(dest="command")
    create = commands.add_parser("create-user", help="Create an account interactively")
    create.add_argument("--username", help="Unique account username")
    create.add_argument("--display-name", help="Name shown in the application")
    create.add_argument("--role", choices=("user", "admin"), default="user")
    commands.add_parser(
        "init-demo-users", help="Create the two synthetic-data demo accounts"
    )


def run_account_command(arguments: argparse.Namespace) -> int:
    """Run local account setup against the same DAP_DB_PATH used by FastAPI."""
    path = Path(os.getenv("DAP_DB_PATH", "data/dap.db")).resolve()
    try:
        if arguments.command == "init-demo-users":
            initialize_database(path)
            _initialize_demo_users(path)
        else:
            username = arguments.username or input("Username: ")
            display_name = arguments.display_name or input("Display name: ") or username
            password = getpass("Password (15+ characters): ")
            if password != getpass("Confirm password: "):
                raise ValueError("Passwords do not match.")
            validate_new_password(password)
            encoded_hash = hash_password(password)
            initialize_database(path)
            account = create_user(
                path,
                username=username,
                display_name=display_name,
                password_hash=encoded_hash,
                role=arguments.role,
            )
            print(f"Created account: {account.username} ({account.role}).")
        return 0
    except (EOFError, KeyboardInterrupt):
        print("Account setup cancelled.", file=sys.stderr)
    except (ValueError, sqlite3.Error, OSError, HashGenerationError) as exc:
        print(f"Account setup failed: {exc}", file=sys.stderr)
    return 1


def _initialize_demo_users(path: Path) -> None:
    """Create missing demo accounts without resetting existing passwords or roles."""
    for username, display_name, role in _DEMO_ACCOUNTS:
        if get_user_by_username(path, username) is not None:
            print(f"Skipped existing account: {username} (unchanged).")
            continue
        try:
            create_user(
                path,
                username=username,
                display_name=display_name,
                password_hash=hash_password(_DEMO_PASSWORD),
                role=role,
            )
        except DuplicateUsername:
            # Another setup process may have created it after the lookup.
            print(f"Skipped existing account: {username} (unchanged).")
        else:
            print(f"Created demo account: {username} ({role}).")
    print(f"Demo password for newly created accounts: {_DEMO_PASSWORD}")
