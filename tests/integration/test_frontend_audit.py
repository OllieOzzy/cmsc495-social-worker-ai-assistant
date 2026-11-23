"""Read real account history through the administrator's Streamlit view."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from documentation_assistant.backend.db.audit import record_authentication_event
from documentation_assistant.frontend import reports
from tests.auth_helpers import sign_in_app
from tests.integration.test_frontend_user_management import PASSWORD, button

APP_PATH = Path(reports.__file__).with_name("app.py")


def test_admin_reads_account_actions_without_secrets_and_can_return_to_management(
    backend_for_ui,
):
    """Creation from the GUI appears with the signed-in actor and no credential values."""
    app = sign_in_app(AppTest.from_file(str(APP_PATH), default_timeout=15))
    button(app, "Manage users").click().run()
    app.text_input(key="new_username").set_value("audit-user")
    app.text_input(key="new_display_name").set_value("Audit User")
    app.text_input(key="new_password").set_value(PASSWORD)
    app.text_input(key="new_password_confirmation").set_value(PASSWORD)
    button(app, "Create account").click().run()
    app.toggle(key="show_user_audit").set_value(True).run()
    assert not app.exception, app.exception
    frame = app.dataframe[0].value
    assert frame.iloc[0]["Actor"] == "workflow-admin"
    assert frame.iloc[0]["Account"] == "audit-user"
    assert frame.iloc[0]["Action"] == "account created"
    assert frame.iloc[0]["Actor ID"] == str(backend_for_ui.account.user_id)
    assert PASSWORD not in frame.to_string()
    assert "$argon2" not in frame.to_string()
    button(app, "Refresh history").click().run()
    assert not app.exception, app.exception
    app.toggle(key="show_user_audit").set_value(False).run()
    assert not app.exception, app.exception
    assert any(widget.label == "Create account" for widget in app.button)


def test_admin_reads_authentication_failures_in_existing_history(backend_for_ui):
    """The existing history view shows unknown login targets and still refreshes."""
    record_authentication_event(
        backend_for_ui.app.state.database_path, "unknown-user", "login_throttled"
    )
    app = sign_in_app(AppTest.from_file(str(APP_PATH), default_timeout=15))
    button(app, "Manage users").click().run()
    app.toggle(key="show_user_audit").set_value(True).run()
    assert not app.exception, app.exception
    frame = app.dataframe[0].value
    assert frame.iloc[0]["Account"] == "unknown-user"
    assert frame.iloc[0]["Account ID"] == ""
    assert frame.iloc[0]["Actor"] == "Authentication attempt"
    assert frame.iloc[0]["Action"] == "login throttled"
    button(app, "Refresh history").click().run()
    assert not app.exception, app.exception
