"""Verify self-service password form validation and browser state cleanup."""

from unittest.mock import MagicMock, Mock

import pytest

from documentation_assistant.frontend import account, auth_state

PASSWORD = "A replacement frontend password!"


class RerunRequested(Exception):
    """Stop rendering where Streamlit would start a fresh application run."""


@pytest.fixture
def ui(monkeypatch):
    """Share one isolated session with the real credential cleanup helper."""
    view = MagicMock()
    view.session_state = {"auth_user": {"user_id": "current-user", "role": "user"}}
    view.button.return_value = False
    view.form_submit_button.return_value = False
    view.rerun.side_effect = RerunRequested
    monkeypatch.setattr(account, "st", view)
    monkeypatch.setattr(auth_state, "st", view)
    return view


def test_password_navigation_requires_a_signed_in_account(ui):
    """Do not show settings to anonymous sessions."""
    ui.session_state.clear()
    assert not account.show_password_navigation()
    ui.button.assert_not_called()


@pytest.mark.parametrize(
    "initial, expected", [("reports", "password"), ("password", "reports")]
)
def test_password_navigation_preserves_selected_saved_report(ui, initial, expected):
    """Opening or leaving settings does not replace saved report selection."""
    ui.session_state.update(app_view=initial, report={"report_id": "saved"})
    ui.button.return_value = True
    with pytest.raises(RerunRequested):
        account.show_password_navigation()
    assert ui.session_state["app_view"] == expected
    assert ui.session_state["report"] == {"report_id": "saved"}


@pytest.mark.parametrize(
    "values, message",
    [
        (["", PASSWORD, PASSWORD], "Enter your current password."),
        (["current", PASSWORD, "Different"], "Passwords do not match."),
        (
            ["current", "short", "short"],
            "New account passwords must contain 15 to 1024 characters.",
        ),
    ],
)
def test_invalid_input_is_rejected_without_retaining_passwords(
    ui, monkeypatch, values, message
):
    """Reject common mistakes before sending a sensitive request."""
    request = Mock()
    monkeypatch.setattr(account, "request_api", request)
    ui.form_submit_button.return_value = True
    ui.text_input.side_effect = values
    ui.session_state["account_current_password"] = "private"
    account.show_password_change()
    request.assert_not_called()
    ui.error.assert_called_once_with(message)
    assert "account_current_password" not in ui.session_state


@pytest.mark.parametrize("succeeds", [False, True])
def test_change_sends_no_account_id_and_clears_state_only_on_success(
    ui, monkeypatch, succeeds
):
    """A failed current-password check retains the session but clears secret inputs."""
    request = Mock(return_value=True if succeeds else None)
    monkeypatch.setattr(account, "request_api", request)
    ui.form_submit_button.return_value = True
    ui.text_input.side_effect = ["current", PASSWORD, PASSWORD]
    ui.session_state.update(
        auth_token="private-token",
        report={"notes": "Private notes."},
        account_new_password=PASSWORD,
    )
    if succeeds:
        with pytest.raises(RerunRequested):
            account.show_password_change()
        assert set(ui.session_state) == {"auth_notice"}
    else:
        account.show_password_change()
        assert ui.session_state["auth_token"] == "private-token"
        assert "account_new_password" not in ui.session_state
    request.assert_called_once_with(
        "POST",
        "/auth/change-password",
        payload={"current_password": "current", "new_password": PASSWORD},
    )
