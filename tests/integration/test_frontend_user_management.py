"""Drive admin account creation and activation through real Streamlit forms."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from documentation_assistant.backend.auth.passwords import hash_password
from documentation_assistant.backend.db.users import create_user, get_user_by_username
from documentation_assistant.frontend import reports
from tests.auth_helpers import sign_in_app

APP_PATH = Path(reports.__file__).with_name("app.py")
PASSWORD = "Synthetic user management password!"


def button(app, label):
    """Find a visible action without depending on its position in the sidebar."""
    return next(item for item in app.button if item.label == label)


def test_admin_creates_account_in_gui_and_new_user_can_sign_in(backend_for_ui):
    """A GUI-created regular account works immediately and has no admin navigation."""
    app = sign_in_app(AppTest.from_file(str(APP_PATH), default_timeout=15))
    button(app, "Manage users").click().run()
    assert not app.exception, app.exception
    app.text_input(key="new_username").set_value("new-user")
    app.text_input(key="new_display_name").set_value("New User")
    app.text_input(key="new_password").set_value(PASSWORD)
    app.text_input(key="new_password_confirmation").set_value(PASSWORD)
    button(app, "Create account").click().run()
    assert not app.exception, app.exception
    account = get_user_by_username(backend_for_ui.app.state.database_path, "new-user")
    assert account.role == "user"
    assert app.text_input(key="new_password").value == ""
    assert app.text_input(key="new_password_confirmation").value == ""
    assert any("Created account: new-user" in notice.value for notice in app.success)
    button(app, "Sign out").click().run()
    sign_in_app(app, "new-user", PASSWORD)
    assert app.session_state["auth_user"]["username"] == "new-user"
    assert all(item.label != "Manage users" for item in app.button)
    app.session_state["app_view"] = "users"
    app.run()
    assert not app.exception, app.exception
    assert not app.dataframe
    assert all(item.label != "Create account" for item in app.button)


def test_gui_deactivation_revokes_session_and_reactivation_requires_fresh_login(
    backend_for_ui,
):
    """A disabled user is returned to login while the admin keeps control."""
    path = backend_for_ui.app.state.database_path
    account = create_user(
        path,
        username="regular",
        display_name="Regular User",
        password_hash=hash_password(PASSWORD),
    )
    regular = sign_in_app(
        AppTest.from_file(str(APP_PATH), default_timeout=15), "regular", PASSWORD
    )
    old_token = regular.session_state["auth_token"]
    admin = sign_in_app(AppTest.from_file(str(APP_PATH), default_timeout=15))
    button(admin, "Manage users").click().run()
    admin.selectbox(key="managed_user_id").set_value(str(account.user_id)).run()
    next(item for item in admin.checkbox if item.label == "Account active").set_value(
        False
    )
    button(admin, "Save account status").click().run()
    assert not admin.exception, admin.exception
    assert not get_user_by_username(path, "regular").is_active
    regular.run()
    assert not regular.exception, regular.exception
    assert "auth_token" not in regular.session_state
    assert not regular.text_area
    next(item for item in admin.checkbox if item.label == "Account active").set_value(
        True
    )
    button(admin, "Save account status").click().run()
    assert not admin.exception, admin.exception
    assert get_user_by_username(path, "regular").is_active
    assert (
        backend_for_ui.get(
            "/auth/me", headers={"Authorization": f"Bearer {old_token}"}
        ).status_code
        == 401
    )
    sign_in_app(regular, "regular", PASSWORD)
    assert not regular.exception, regular.exception
    assert regular.session_state["auth_token"] != old_token


def test_admin_cannot_disable_own_account_in_gui(backend_for_ui):
    """Self-deactivation controls are visibly disabled rather than failing silently."""
    app = sign_in_app(AppTest.from_file(str(APP_PATH), default_timeout=15))
    button(app, "Manage users").click().run()
    app.selectbox(key="managed_user_id").set_value(
        str(backend_for_ui.account.user_id)
    ).run()
    assert not app.exception, app.exception
    assert next(
        item for item in app.checkbox if item.label == "Account active"
    ).disabled
    assert button(app, "Save account status").disabled
    button(app, "Back to reports").click().run()
    assert not app.exception, app.exception
    assert any("Session Notes" in item.label for item in app.text_area)
