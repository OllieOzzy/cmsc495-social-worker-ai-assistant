"""Verify GUI renaming and account continuity through real Streamlit and FastAPI."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from documentation_assistant.backend.auth.passwords import hash_password
from documentation_assistant.backend.db.users import create_user
from documentation_assistant.frontend import reports
from tests.auth_helpers import sign_in_app

APP_PATH = Path(reports.__file__).with_name("app.py")
PASSWORD = "Synthetic rename test password!"


def button(app, label):
    """Select actions by visible label rather than their sidebar position."""
    return next(item for item in app.button if item.label == label)


def select_account(admin, user_id):
    """Navigate to the real account form for one stable account ID."""
    button(admin, "Manage users").click().run()
    admin.selectbox(key="managed_user_id").set_value(str(user_id)).run()
    assert not admin.exception, admin.exception


def test_admin_renames_user_and_owner_recovers_same_reports(backend_for_ui):
    """Renaming the login name invalidates old sessions without losing saved notes."""
    identity = create_user(
        backend_for_ui.app.state.database_path,
        username="regular",
        display_name="Regular User",
        password_hash=hash_password(PASSWORD),
    )
    regular = sign_in_app(
        AppTest.from_file(str(APP_PATH), default_timeout=15), "regular", PASSWORD
    )
    next(
        field for field in regular.text_area if "Session Notes" in field.label
    ).set_value("Private notes remain with this account.")
    button(regular, "Written by hand").click().run()
    saved = regular.session_state["report"]
    admin = sign_in_app(AppTest.from_file(str(APP_PATH), default_timeout=15))
    select_account(admin, identity.user_id)
    next(
        field for field in admin.text_input if field.label == "New username"
    ).set_value("renamed-regular")
    next(
        field for field in admin.text_input if field.label == "New display name"
    ).set_value("Renamed Regular")
    next(
        field
        for field in admin.checkbox
        if field.label
        == "I understand a username change signs the user out of all sessions"
    ).set_value(True)
    button(admin, "Save account names").click().run()
    assert not admin.exception, admin.exception
    assert any(
        "Updated account names: renamed-regular" in notice.value
        for notice in admin.success
    )
    regular.run()
    assert not regular.exception, regular.exception
    assert "auth_token" not in regular.session_state
    sign_in_app(regular, "renamed-regular", PASSWORD)
    assert regular.session_state["auth_user"]["user_id"] == str(identity.user_id)
    button(regular, "Open report").click().run()
    assert regular.session_state["report"] == saved


def test_display_name_edit_updates_signed_in_user_without_logout(backend_for_ui):
    """A cosmetic rename needs no revocation checkbox and preserves the current token."""
    identity = create_user(
        backend_for_ui.app.state.database_path,
        username="regular",
        display_name="Regular User",
        password_hash=hash_password(PASSWORD),
    )
    regular = sign_in_app(
        AppTest.from_file(str(APP_PATH), default_timeout=15), "regular", PASSWORD
    )
    original_token = regular.session_state["auth_token"]
    admin = sign_in_app(AppTest.from_file(str(APP_PATH), default_timeout=15))
    select_account(admin, identity.user_id)
    next(
        field for field in admin.text_input if field.label == "New display name"
    ).set_value("Updated Display Name")
    button(admin, "Save account names").click().run()
    assert not admin.exception, admin.exception
    regular.run()
    assert not regular.exception, regular.exception
    assert regular.session_state["auth_token"] == original_token
    assert regular.session_state["auth_user"]["display_name"] == "Updated Display Name"


def test_admin_self_username_rename_returns_to_login(backend_for_ui):
    """The current admin signs back in with the new name and the same password."""
    app = sign_in_app(AppTest.from_file(str(APP_PATH), default_timeout=15))
    select_account(app, backend_for_ui.account.user_id)
    next(field for field in app.text_input if field.label == "New username").set_value(
        "renamed-admin"
    )
    next(
        field
        for field in app.checkbox
        if field.label
        == "I understand a username change signs the user out of all sessions"
    ).set_value(True)
    button(app, "Save account names").click().run()
    assert not app.exception, app.exception
    assert "auth_token" not in app.session_state
    assert "app_view" not in app.session_state
    assert any(item.label == "Sign in" for item in app.button)
    sign_in_app(app, "renamed-admin")
    assert not app.exception, app.exception
    assert app.session_state["auth_user"]["role"] == "admin"
    assert app.session_state["auth_user"]["user_id"] == str(
        backend_for_ui.account.user_id
    )
