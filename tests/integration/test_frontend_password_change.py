"""Drive self-service password changes through real Streamlit and FastAPI."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from documentation_assistant.backend.auth.passwords import hash_password
from documentation_assistant.backend.db.users import create_user
from documentation_assistant.frontend import reports
from tests.auth_helpers import sign_in_app

APP_PATH = Path(reports.__file__).with_name("app.py")
OLD_PASSWORD = "Synthetic current frontend password!"
NEW_PASSWORD = "Synthetic new frontend password!"


def button(app, label):
    """Find a visible action by label rather than its position in the sidebar."""
    return next(item for item in app.button if item.label == label)


def fill_passwords(app, current):
    """Fill the three fields without adding an account ID to the request."""
    app.text_input(key="account_current_password").set_value(current)
    app.text_input(key="account_new_password").set_value(NEW_PASSWORD)
    app.text_input(key="account_password_confirmation").set_value(NEW_PASSWORD)


@pytest.mark.parametrize("role", ["user", "admin"])
def test_password_change_verifies_current_password_and_returns_to_login(
    backend_for_ui, role
):
    """Both roles can change their own password without losing saved reports."""
    username = "regular" if role == "user" else "second-admin"
    identity = create_user(
        backend_for_ui.app.state.database_path,
        username=username,
        display_name=username.title(),
        password_hash=hash_password(OLD_PASSWORD),
        role=role,
    )
    app = sign_in_app(
        AppTest.from_file(str(APP_PATH), default_timeout=15), username, OLD_PASSWORD
    )
    next(field for field in app.text_area if "Session Notes" in field.label).set_value(
        "Preserved private synthetic notes."
    )
    button(app, "Written by hand").click().run()
    saved = app.session_state["report"]
    token = app.session_state["auth_token"]
    button(app, "Change password").click().run()
    assert not app.exception, app.exception
    assert not app.text_area
    fill_passwords(app, "Incorrect current password")
    button(app, "Change password").click().run()
    assert not app.exception, app.exception
    assert any(error.value == "Current password is incorrect." for error in app.error)
    assert app.session_state["auth_token"] == token
    app.session_state["prepared_pdf"] = b"Private PDF"
    fill_passwords(app, OLD_PASSWORD)
    button(app, "Change password").click().run()
    assert not app.exception, app.exception
    for key in (
        "auth_token",
        "auth_user",
        "report",
        "prepared_pdf",
        "account_current_password",
        "account_new_password",
    ):
        assert key not in app.session_state
    assert any(item.label == "Sign in" for item in app.button)
    assert (
        backend_for_ui.get(
            "/auth/me", headers={"Authorization": f"Bearer {token}"}
        ).status_code
        == 401
    )
    assert (
        backend_for_ui.post(
            "/auth/login", json={"username": username, "password": OLD_PASSWORD}
        ).status_code
        == 401
    )
    sign_in_app(app, username, NEW_PASSWORD)
    assert not app.exception, app.exception
    assert app.session_state["auth_user"]["user_id"] == str(identity.user_id)
    assert app.session_state["auth_user"]["role"] == role
    button(app, "Open report").click().run()
    assert app.session_state["report"] == saved


def test_leaving_password_settings_preserves_selected_saved_report(backend_for_ui):
    """Back to reports restores selection without submitting a password change."""
    saved = backend_for_ui.post(
        "/reports/manual", json={"notes": "Saved source notes."}
    ).json()
    app = sign_in_app(AppTest.from_file(str(APP_PATH), default_timeout=15))
    button(app, "Open report").click().run()
    button(app, "Change password").click().run()
    assert not app.exception, app.exception
    button(app, "Back to reports").click().run()
    assert not app.exception, app.exception
    assert app.session_state["report"] == saved
    assert any(field.value == "Saved source notes." for field in app.text_area)
