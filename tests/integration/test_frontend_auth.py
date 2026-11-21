"""Exercise real Streamlit login, role controls, logout, and user switching."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from documentation_assistant.backend.auth.passwords import hash_password
from documentation_assistant.backend.db.connection import connect
from documentation_assistant.backend.db.users import create_user
from documentation_assistant.frontend import reports
from tests.auth_helpers import sign_in_app

APP_PATH = Path(reports.__file__).with_name("app.py")
PASSWORD = "Synthetic frontend login password!"


@pytest.fixture
def accounts(backend_for_ui):
    """Add two users to the real backend used by the browser's test transport."""
    encoded = hash_password(PASSWORD)
    for name in ("alice", "bobby"):
        create_user(
            backend_for_ui.app.state.database_path,
            username=name,
            display_name=name.title(),
            password_hash=encoded,
        )
    return backend_for_ui


def button(app, label):
    """Select a visible button by its user-facing label."""
    return next(item for item in app.button if item.label == label)


def new_app():
    """Keep widget interactions on the real app entry point."""
    return AppTest.from_file(str(APP_PATH), default_timeout=15)


def create_from_ui(app):
    """Save a handwritten draft containing distinctive synthetic source notes."""
    next(field for field in app.text_area if "Session Notes" in field.label).set_value(
        "Alice's private synthetic notes."
    )
    button(app, "Written by hand").click().run()
    assert not app.exception, app.exception
    return app.session_state["report"]


def test_signed_out_and_wrong_password_never_render_report_screens(accounts):
    """The login gate stays closed after an incorrect password."""
    app = new_app().run()
    assert not app.text_area
    app.text_input(key="login_username").set_value("alice")
    app.text_input(key="login_password").set_value("Incorrect password")
    button(app, "Sign in").click().run()
    assert not app.exception, app.exception
    assert not app.text_area
    assert "auth_token" not in app.session_state
    assert any("Invalid username or password" in error.value for error in app.error)


def test_logout_and_user_switch_clear_reports_filters_passwords_and_pdf_state(accounts):
    """A second user in the same browser cannot inherit the previous user's data."""
    app = sign_in_app(new_app(), "alice", PASSWORD)
    report = create_from_ui(app)
    assert report["owner_id"] == app.session_state["auth_user"]["user_id"]
    token = app.session_state["auth_token"]
    app.session_state["prepared_pdf"] = b"Private PDF bytes"
    app.session_state["active_report_filters"] = {"student_name": "Private name"}
    app.session_state["pending_report_id"] = report["report_id"]
    button(app, "Sign out").click().run()
    assert not app.exception, app.exception
    for key in (
        "auth_token",
        "auth_user",
        "report",
        "prepared_pdf",
        "pending_report_id",
        "active_report_filters",
    ):
        assert key not in app.session_state
    assert not app.text_area
    assert (
        accounts.get(
            "/auth/me", headers={"Authorization": f"Bearer {token}"}
        ).status_code
        == 401
    )
    sign_in_app(app, "bobby", PASSWORD)
    assert "report" not in app.session_state
    assert all("Alice's private" not in widget.value for widget in app.text_area)
    assert any("No saved reports" in caption.value for caption in app.caption)


def test_admin_reviews_others_read_only_and_owner_cannot_approve_or_reopen(accounts):
    """Admin review controls and owner editing controls are separate in the UI."""
    app = sign_in_app(new_app(), "alice", PASSWORD)
    report = create_from_ui(app)
    assert all(item.label != "Approve saved draft" for item in app.button)
    for name, label in reports.DAP_FIELDS.items():
        next(widget for widget in app.text_area if widget.label == label).set_value(
            f"Synthetic {name}."
        )
    button(app, "Save draft").click().run()
    button(app, "Sign out").click().run()
    sign_in_app(app)
    button(app, "Open report").click().run()
    assert not app.exception, app.exception
    assert button(app, "Save draft").disabled
    assert all(item.label != "Delete draft" for item in app.button)
    assert all(field.disabled for field in app.text_area)
    button(app, "Approve saved draft").click().run()
    assert not app.exception, app.exception
    assert app.session_state["report"]["approved_by"] == "Taylor Example"
    assert any(item.label == "Reopen as draft" for item in app.button)
    button(app, "Sign out").click().run()
    sign_in_app(app, "alice", PASSWORD)
    button(app, "Open report").click().run()
    assert app.session_state["report"]["report_id"] == report["report_id"]
    assert button(app, "Save draft").disabled
    assert all(
        item.label not in ("Approve saved draft", "Reopen as draft", "Delete draft")
        for item in app.button
    )
    assert any(item.label == "Prepare PDF" for item in app.button)


@pytest.mark.parametrize("reason", ["expired", "revoked"])
def test_expired_or_revoked_session_clears_cached_reports_and_returns_to_login(
    accounts, reason
):
    """Expiry and a backend 401 both remove report content from the rendered page."""
    app = sign_in_app(new_app(), "alice", PASSWORD)
    create_from_ui(app)
    app.session_state["prepared_pdf"] = b"Private"
    if reason == "expired":
        app.session_state["auth_expires_at"] = "2000-01-01T00:00:00Z"
    else:
        accounts.post(
            "/auth/logout",
            headers={"Authorization": f"Bearer {app.session_state['auth_token']}"},
        ).raise_for_status()
    app.run()
    assert not app.exception, app.exception
    assert not app.text_area
    assert "report" not in app.session_state
    assert "prepared_pdf" not in app.session_state
    assert "auth_token" not in app.session_state
    assert any(item.label == "Sign in" for item in app.button)


def test_admin_demotion_clears_cached_foreign_report(accounts):
    """The next rerun refreshes roles and removes content the user can no longer read."""
    owner = sign_in_app(new_app(), "alice", PASSWORD)
    create_from_ui(owner)
    app = sign_in_app(new_app())
    button(app, "Open report").click().run()
    assert "report" in app.session_state
    with connect(accounts.app.state.database_path) as connection:
        connection.execute(
            "UPDATE users SET role = 'user' WHERE username = 'workflow-admin'"
        )
    app.run()
    assert not app.exception, app.exception
    assert "report" not in app.session_state
    assert app.session_state["auth_user"]["role"] == "user"
    assert all("Alice's private" not in widget.value for widget in app.text_area)
