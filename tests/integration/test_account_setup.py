"""Verify terminal account setup with real Argon2 hashes and temporary SQLite."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from documentation_assistant import launcher
from documentation_assistant.backend.auth import cli
from documentation_assistant.backend.auth.passwords import (
    hash_password,
    verify_password,
)
from documentation_assistant.backend.db.connection import initialize_database
from documentation_assistant.backend.db.users import create_user, get_user_by_username


@pytest.fixture
def account_path(monkeypatch, tmp_path):
    """Direct setup commands to a fresh database without touching saved reports."""
    path = tmp_path / "accounts.db"
    monkeypatch.setenv("DAP_DB_PATH", str(path))
    return path


@pytest.mark.parametrize("role", ["user", "admin"])
def test_interactive_command_creates_account_with_encoded_password(
    account_path, monkeypatch, capsys, role
):
    """Passwords are confirmed through getpass and never echoed in command output."""
    password = "A longer test password!"
    monkeypatch.setattr(cli, "getpass", lambda prompt: password)
    assert (
        launcher.main(
            [
                "create-user",
                "--username",
                " Robert ",
                "--display-name",
                "Robert Example",
                "--role",
                role,
            ]
        )
        == 0
    )

    account = get_user_by_username(account_path, "robert")
    assert account.role == role
    assert account.display_name == "Robert Example"
    assert verify_password(password, account.password_hash)
    assert account.password_hash != password
    output = capsys.readouterr()
    assert password not in output.out + output.err
    assert account.password_hash not in output.out + output.err


def test_account_details_can_be_entered_at_prompts(account_path, monkeypatch):
    """A display name can default to the username; regular-user role is the default."""
    answers = iter(["robert", ""])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    monkeypatch.setattr(cli, "getpass", lambda prompt: "A longer test password!")

    assert launcher.main(["create-user"]) == 0

    account = get_user_by_username(account_path, "robert")
    assert account.display_name == "robert"
    assert account.role == "user"


@pytest.mark.parametrize(
    "passwords", [("short", "short"), ("a" * 1025, "a" * 1025), ("first", "different")]
)
def test_invalid_passwords_do_not_create_a_database(
    account_path, monkeypatch, passwords
):
    """Reject weak, oversized, or mismatched passwords before any account write."""
    answers = iter(passwords)
    monkeypatch.setattr(cli, "getpass", lambda prompt: next(answers))

    assert (
        launcher.main(
            [
                "create-user",
                "--username",
                "robert",
                "--display-name",
                "Robert Example",
            ]
        )
        == 1
    )
    assert not account_path.exists()


def test_duplicate_account_does_not_replace_credentials_or_role(
    account_path, monkeypatch, capsys
):
    """Creating an existing username must not reset its password or promote its role."""
    initialize_database(account_path)
    original = create_user(
        account_path,
        username="user",
        display_name="Original User",
        password_hash=hash_password("Original long password!"),
    )
    monkeypatch.setattr(cli, "getpass", lambda prompt: "Different long password!")

    assert (
        launcher.main(
            [
                "create-user",
                "--username",
                "USER",
                "--display-name",
                "Replacement",
                "--role",
                "admin",
            ]
        )
        == 1
    )

    assert get_user_by_username(account_path, "user") == original
    assert "Username already exists" in capsys.readouterr().err


def test_demo_setup_creates_two_accounts_and_is_safe_to_repeat(account_path):
    """Seed the agreed public credentials once without replacing their salted hashes."""
    assert launcher.main(["init-demo-users"]) == 0
    admin = get_user_by_username(account_path, "admin")
    user = get_user_by_username(account_path, "user")
    assert admin.role == "admin"
    assert user.role == "user"
    assert verify_password("password1234", admin.password_hash)
    assert verify_password("password1234", user.password_hash)
    assert admin.password_hash != user.password_hash

    assert launcher.main(["init-demo-users"]) == 0
    assert get_user_by_username(account_path, "admin") == admin
    assert get_user_by_username(account_path, "user") == user


def test_demo_setup_preserves_existing_non_demo_account(account_path):
    """A matching demo username never grants a new role or overwrites credentials."""
    initialize_database(account_path)
    existing = create_user(
        account_path,
        username="admin",
        display_name="Existing Regular User",
        password_hash=hash_password("An existing long password!"),
        role="user",
    )

    assert launcher.main(["init-demo-users"]) == 0

    assert get_user_by_username(account_path, "admin") == existing
    assert get_user_by_username(account_path, "user").role == "user"


def test_cancelled_password_prompt_creates_no_account(
    account_path, monkeypatch, capsys
):
    """Terminal cancellation should exit cleanly without writing credentials."""

    def cancel(prompt):
        """Simulate an interrupted hidden password prompt."""
        raise EOFError

    monkeypatch.setattr(cli, "getpass", cancel)
    assert (
        launcher.main(
            [
                "create-user",
                "--username",
                "robert",
                "--display-name",
                "Robert Example",
            ]
        )
        == 1
    )
    assert not account_path.exists()
    assert "cancelled" in capsys.readouterr().err


def test_module_command_provisions_accounts_from_another_directory(
    account_path, tmp_path
):
    """Exercise the actual module entry point rather than only its Python handlers."""
    source = Path(__file__).resolve().parents[2] / "src"
    process = subprocess.run(
        [sys.executable, "-m", "documentation_assistant.launcher", "init-demo-users"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(source)},
        capture_output=True,
        text=True,
        timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )

    assert process.returncode == 0, process.stdout + process.stderr
    assert get_user_by_username(account_path, "admin").role == "admin"
    assert get_user_by_username(account_path, "user").role == "user"
