"""Verify admin navigation, account forms, and bounded user-list rendering."""

from unittest.mock import MagicMock, Mock

import pytest

from documentation_assistant.frontend import users

ACCOUNT = {
    "user_id": "other-id",
    "username": "other",
    "display_name": "Other User",
    "role": "user",
    "is_active": True,
}
PASSWORD = "A long management test password!"


class RerunRequested(Exception):
    """Stop the current render where Streamlit would rerun the application."""


@pytest.fixture
def ui(monkeypatch):
    """Isolate account widgets and prevent accidental real backend requests."""
    view = MagicMock()
    view.session_state = {"auth_user": {"user_id": "admin-id", "role": "admin"}}
    view.rerun.side_effect = RerunRequested
    view.button.return_value = False
    view.form_submit_button.return_value = False
    view.checkbox.return_value = True
    view.selectbox.side_effect = lambda label, options, **kwargs: options[0]
    monkeypatch.setattr(users, "st", view)
    monkeypatch.setattr(users, "is_admin", Mock(return_value=True))
    return view


@pytest.fixture
def api(monkeypatch):
    """Expose request arguments without starting FastAPI."""
    request = Mock()
    monkeypatch.setattr(users, "request_api", request)
    return request


def test_regular_user_cannot_open_management_or_keep_admin_view(ui, api, monkeypatch):
    """Hiding navigation is backed by a screen-level check as well as API permissions."""
    ui.session_state["app_view"] = "users"
    monkeypatch.setattr(users, "is_admin", Mock(return_value=False))
    assert not users.show_admin_navigation()
    assert "app_view" not in ui.session_state
    users.show_user_management()
    api.assert_not_called()
    ui.error.assert_called_once_with("Administrator access required.")


@pytest.mark.parametrize(
    "initial, expected", [("reports", "users"), ("users", "reports")]
)
def test_admin_navigation_toggles_without_replacing_saved_report(ui, initial, expected):
    """Changing screens preserves the selected saved report."""
    ui.session_state.update(app_view=initial, report={"report_id": "saved"})
    ui.button.return_value = True
    with pytest.raises(RerunRequested):
        users.show_admin_navigation()
    assert ui.session_state["app_view"] == expected
    assert ui.session_state["report"] == {"report_id": "saved"}


@pytest.mark.parametrize(
    "values, message",
    [
        (["", "Name", PASSWORD, PASSWORD], "Enter a username and display name."),
        (["new-user", "Name", PASSWORD, "Different"], "Passwords do not match."),
        (
            ["new-user", "Name", "short", "short"],
            "New account passwords must contain 15 to 1024 characters.",
        ),
    ],
)
def test_invalid_creation_stays_local_and_clears_password_widgets(
    ui, api, values, message
):
    """Reject common input errors before sending account credentials."""
    ui.form_submit_button.return_value = True
    ui.text_input.side_effect = values
    ui.session_state.update(new_password=values[2], new_password_confirmation=values[3])
    users._create_account_form()
    api.assert_not_called()
    ui.error.assert_called_once_with(message)
    assert "new_password" not in ui.session_state
    assert "new_password_confirmation" not in ui.session_state


@pytest.mark.parametrize("succeeds", [False, True])
def test_creation_sends_chosen_role_and_clears_credentials(ui, api, succeeds):
    """A rejected request never shows a success notice or retains password fields."""
    ui.form_submit_button.return_value = True
    ui.text_input.side_effect = ["new-user", "New User", PASSWORD, PASSWORD]
    ui.session_state.update(new_password=PASSWORD, new_password_confirmation=PASSWORD)
    api.return_value = {**ACCOUNT, "username": "new-user"} if succeeds else None
    if succeeds:
        with pytest.raises(RerunRequested):
            users._create_account_form()
        assert ui.session_state["users_offset"] == 0
    else:
        users._create_account_form()
        assert "user_management_notice" not in ui.session_state
    assert "new_password" not in ui.session_state
    api.assert_called_once_with(
        "POST",
        "/users",
        payload={
            "username": "new-user",
            "display_name": "New User",
            "role": "user",
            "password": PASSWORD,
        },
    )


def test_own_status_controls_are_disabled(ui, api):
    """An administrator cannot accidentally disable the account they are using."""
    users._account_status_form([{**ACCOUNT, "user_id": "admin-id", "role": "admin"}])
    assert ui.checkbox.call_args.kwargs["disabled"]
    assert ui.form_submit_button.call_args.kwargs["disabled"]
    api.assert_not_called()


def test_status_change_sends_only_the_activation_flag(ui, api):
    """Changing activation cannot change role or password as a side effect."""
    ui.checkbox.return_value = False
    ui.form_submit_button.return_value = True
    api.return_value = {**ACCOUNT, "is_active": False}
    with pytest.raises(RerunRequested):
        users._account_status_form([ACCOUNT])
    api.assert_called_once_with(
        "PATCH", "/users/other-id", payload={"is_active": False}
    )


@pytest.mark.parametrize(
    "label, offset, expected", [("Previous users", 25, 0), ("Next users", 0, 25)]
)
def test_account_pagination_requests_one_extra_row(ui, api, label, offset, expected):
    """Show a bounded page and advance without loading the entire account table."""
    ui.session_state["users_offset"] = offset
    ui.button.side_effect = lambda text, **kwargs: text == label and not kwargs.get(
        "disabled", False
    )
    api.return_value = [{**ACCOUNT, "user_id": str(index)} for index in range(26)]
    with pytest.raises(RerunRequested):
        users.show_user_management()
    api.assert_called_once_with("GET", "/users", params={"limit": 26, "offset": offset})
    assert len(ui.dataframe.call_args.args[0]) == 25
    assert ui.session_state["users_offset"] == expected
