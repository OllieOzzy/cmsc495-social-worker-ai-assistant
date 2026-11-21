"""Verify session cleanup, login gating, and role changes without a web server."""

from unittest.mock import MagicMock, Mock

import pytest

from documentation_assistant.frontend import auth, auth_state

USER = {
    "user_id": "alice-id",
    "username": "alice",
    "display_name": "Alice",
    "role": "user",
}


class RerunRequested(Exception):
    """Stop execution at the point where Streamlit would start a fresh render."""


@pytest.fixture
def ui(monkeypatch):
    """Provide one isolated browser session to both authentication modules."""
    view = MagicMock()
    view.session_state = {}
    view.button.return_value = False
    view.form_submit_button.return_value = False
    view.rerun.side_effect = RerunRequested
    monkeypatch.setattr(auth, "st", view)
    monkeypatch.setattr(auth_state, "st", view)
    monkeypatch.setattr(auth, "check_session_expiry", Mock())
    return view


def signed_in(ui):
    """Populate a valid browser session using only synthetic identity fields."""
    ui.session_state.update(
        auth_token="t" * 43,
        auth_expires_at="2099-01-01T00:00:00Z",
        auth_user=dict(USER),
    )


def test_clear_session_removes_all_sensitive_state(ui):
    """Clear tokens, password widgets, report forms, history filters, and PDF bytes."""
    ui.session_state.update(
        auth_token="secret",
        login_password="private",
        report={"notes": "Private"},
        source_123="Private",
        prepared_pdf=b"private",
        history_offset=25,
        active_report_filters={"student_name": "Private"},
    )
    auth_state.clear_session("Signed out.")
    assert ui.session_state == {"auth_notice": "Signed out."}


@pytest.mark.parametrize(
    "expiry", [None, "bad", "2000-01-01T00:00:00Z", "2099-01-01T00:00:00", 123]
)
def test_missing_or_invalid_expiry_fails_closed(ui, expiry):
    """A missing timezone or malformed deadline cannot extend a session."""
    ui.session_state["auth_expires_at"] = expiry
    assert auth_state.session_expired()


def test_valid_session_is_verified_before_reports_render(ui, monkeypatch):
    """The frontend rereads identity rather than trusting cached role information."""
    signed_in(ui)
    api = Mock(return_value=dict(USER))
    monkeypatch.setattr(auth, "request_api", api)
    assert auth.require_login()
    api.assert_called_once_with("GET", "/auth/me", timeout=3)


def test_backend_outage_does_not_render_cached_reports_or_discard_retry_token(
    ui, monkeypatch
):
    """Keep credentials for retry while the app gate blocks report rendering."""
    signed_in(ui)
    monkeypatch.setattr(auth, "request_api", Mock(return_value=None))
    assert not auth.require_login()
    assert ui.session_state["auth_token"] == "t" * 43
    ui.warning.assert_called_once()


def test_role_change_clears_old_reports_and_keeps_verified_session(ui, monkeypatch):
    """A demoted administrator cannot keep a previous user's report on screen."""
    signed_in(ui)
    ui.session_state["auth_user"]["role"] = "admin"
    ui.session_state["report"] = {"notes": "Other owner's notes."}
    monkeypatch.setattr(auth, "request_api", Mock(return_value=dict(USER)))
    with pytest.raises(RerunRequested):
        auth.require_login()
    assert "report" not in ui.session_state
    assert ui.session_state["auth_user"] == USER
    assert ui.session_state["auth_token"] == "t" * 43


@pytest.mark.parametrize("revoked", [True, None])
def test_sign_out_clears_browser_state_even_if_backend_cannot_confirm(
    ui, monkeypatch, revoked
):
    """Offline sign-out is explicit about the server session's uncertain status."""
    signed_in(ui)
    ui.session_state["report"] = {"notes": "Private notes."}
    monkeypatch.setattr(auth, "request_api", Mock(return_value=revoked))
    with pytest.raises(RerunRequested):
        auth._sign_out()
    assert set(ui.session_state) == {"auth_notice"}
    assert ("could not confirm" in ui.session_state["auth_notice"]) == (revoked is None)


def test_expiry_heartbeat_clears_cached_content(ui):
    """The timer's callback expires an idle page without a report action."""
    ui.session_state.update(
        auth_expires_at="2000-01-01T00:00:00Z", report={"notes": "Private"}
    )
    with pytest.raises(RerunRequested):
        auth._expire_if_needed()
    assert set(ui.session_state) == {"auth_notice"}


def test_login_stores_token_identity_and_expiry_but_not_password(ui, monkeypatch):
    """Successful login clears any previous report and password widget values."""
    ui.form_submit_button.return_value = True
    ui.text_input.side_effect = ["alice", "A private password"]
    ui.session_state.update(
        login_password="A private password", report={"notes": "Old"}
    )
    monkeypatch.setattr(
        auth,
        "request_api",
        Mock(
            return_value={
                "access_token": "t" * 43,
                "expires_at": "2099-01-01T00:00:00Z",
                "user": USER,
            }
        ),
    )
    with pytest.raises(RerunRequested):
        auth._show_login()
    assert set(ui.session_state) == {"auth_token", "auth_expires_at", "auth_user"}
    assert "A private password" not in str(ui.session_state)


@pytest.mark.parametrize(
    "admin, owner, owned",
    [(False, None, False), (False, "alice-id", True), (True, "bobby-id", False)],
)
def test_owner_and_admin_helpers_do_not_confuse_review_access_with_ownership(
    ui, admin, owner, owned
):
    """Administrative review rights do not make the account another report's owner."""
    signed_in(ui)
    ui.session_state["auth_user"]["role"] = "admin" if admin else "user"
    assert auth_state.is_admin() is admin
    assert auth_state.owns_report({"owner_id": owner}) is owned
