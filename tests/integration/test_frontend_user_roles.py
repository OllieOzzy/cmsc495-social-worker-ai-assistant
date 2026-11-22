"""Exercise role changes through Streamlit forms and the real authenticated API."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from documentation_assistant.backend.auth.passwords import hash_password
from documentation_assistant.backend.db.users import create_user
from documentation_assistant.frontend import reports
from tests.auth_helpers import sign_in_app
from tests.integration.test_frontend_user_rename import button, select_account

APP_PATH = Path(reports.__file__).with_name("app.py")
PASSWORD = "Synthetic role management password!"
ACKNOWLEDGEMENT = (
    "I understand this changes permissions and signs the user out of all sessions"
)


def submit_role(app, role):
    """Confirm the role change using visible widgets."""
    next(widget for widget in app.selectbox if widget.label == "New role").set_value(
        role
    )
    next(
        widget for widget in app.checkbox if widget.label == ACKNOWLEDGEMENT
    ).set_value(True)
    button(app, "Save role").click().run()
    assert not app.exception, app.exception


def test_promotion_then_demotion_updates_real_browser_permissions(backend_for_ui):
    """Existing browser sessions return to login, then show the new role's navigation."""
    identity = create_user(
        backend_for_ui.app.state.database_path,
        username="regular",
        display_name="Regular",
        password_hash=hash_password(PASSWORD),
    )
    regular = sign_in_app(
        AppTest.from_file(str(APP_PATH), default_timeout=15), "regular", PASSWORD
    )
    admin = sign_in_app(AppTest.from_file(str(APP_PATH), default_timeout=15))
    select_account(admin, identity.user_id)
    submit_role(admin, "admin")
    regular.run()
    assert not regular.exception, regular.exception
    assert "auth_token" not in regular.session_state
    sign_in_app(regular, "regular", PASSWORD)
    assert regular.session_state["auth_user"]["role"] == "admin"
    assert any(widget.label == "Manage users" for widget in regular.button)
    submit_role(admin, "user")
    regular.run()
    assert "auth_token" not in regular.session_state
    sign_in_app(regular, "regular", PASSWORD)
    assert regular.session_state["auth_user"]["role"] == "user"
    assert all(widget.label != "Manage users" for widget in regular.button)


def test_last_admin_demotion_shows_error_without_signing_out(backend_for_ui):
    """The UI presents the API's protection message and preserves the admin session."""
    app = sign_in_app(AppTest.from_file(str(APP_PATH), default_timeout=15))
    token = app.session_state["auth_token"]
    select_account(app, backend_for_ui.account.user_id)
    submit_role(app, "user")
    assert any("last active administrator" in notice.value for notice in app.error)
    assert app.session_state["auth_token"] == token


def test_self_demotion_returns_to_login_when_another_admin_exists(backend_for_ui):
    """Stepping down removes the management view and cached identity immediately."""
    create_user(
        backend_for_ui.app.state.database_path,
        username="second-admin",
        display_name="Second",
        password_hash=hash_password(PASSWORD),
        role="admin",
    )
    app = sign_in_app(AppTest.from_file(str(APP_PATH), default_timeout=15))
    select_account(app, backend_for_ui.account.user_id)
    submit_role(app, "user")
    assert "auth_token" not in app.session_state
    sign_in_app(app)
    assert app.session_state["auth_user"]["role"] == "user"
    assert all(widget.label != "Manage users" for widget in app.button)
