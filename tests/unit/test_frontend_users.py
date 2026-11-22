"""Verify admin navigation, account forms, and bounded user-list rendering."""

from unittest.mock import MagicMock, Mock

import pytest

from documentation_assistant.frontend import auth_state, users

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


@pytest.mark.parametrize("acknowledged", [False, True])
def test_role_change_requires_confirmation(ui, api, acknowledged):
    """A permission change needs explicit acknowledgement before reaching the API."""
    ui.form_submit_button.return_value = True
    ui.selectbox.side_effect = None
    ui.selectbox.return_value = "admin"
    ui.checkbox.return_value = acknowledged
    api.return_value = {**ACCOUNT, "role": "admin"}
    if acknowledged:
        with pytest.raises(RerunRequested):
            users._role_change_form(ACCOUNT)
        api.assert_called_once_with(
            "PATCH", "/users/other-id/role", payload={"role": "admin"}
        )
        assert (
            "Existing sessions were signed out"
            in ui.session_state["user_management_notice"]
        )
    else:
        users._role_change_form(ACCOUNT)
        api.assert_not_called()
        ui.error.assert_called_once()


def test_unchanged_role_does_not_submit(ui, api):
    """Saving an unchanged role must not revoke sessions."""
    ui.form_submit_button.return_value = True
    users._role_change_form(ACCOUNT)
    api.assert_not_called()
    ui.info.assert_called_once_with("No role change selected.")


def test_failed_role_change_keeps_current_session(ui, api):
    """A rejected last-admin demotion leaves the current screen available."""
    ui.form_submit_button.return_value = True
    api.return_value = None
    users._role_change_form({**ACCOUNT, "role": "admin"})
    ui.rerun.assert_not_called()
    assert "auth_user" in ui.session_state


def test_self_demotion_clears_private_state(ui, api, monkeypatch):
    """A successful self-demotion returns to login with no cached report data."""
    monkeypatch.setattr(auth_state, "st", ui)
    ui.form_submit_button.return_value = True
    ui.session_state.update(auth_token="old", report={"notes": "private"})
    own = {**ACCOUNT, "user_id": "admin-id", "role": "admin"}
    api.return_value = {**own, "role": "user"}
    with pytest.raises(RerunRequested):
        users._role_change_form(own)
    assert ui.session_state == {"auth_notice": "Role updated. Please sign in again."}


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
    assert next(
        call for call in ui.checkbox.call_args_list if call.args[0] == "Account active"
    ).kwargs["disabled"]
    assert next(
        call
        for call in ui.form_submit_button.call_args_list
        if call.args[0] == "Save account status"
    ).kwargs["disabled"]
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


def test_search_is_preserved_in_paginated_requests(ui, api):
    """Send the active query to the backend rather than filtering one loaded page."""
    ui.session_state.update(users_search="  Taylor  ", users_offset=25)
    api.return_value = []
    users.show_user_management()
    api.assert_called_once_with(
        "GET", "/users", params={"limit": 26, "offset": 25, "search": "Taylor"}
    )
    ui.info.assert_called_once_with("No matching accounts.")


def test_history_view_skips_account_loading(ui, api, monkeypatch):
    """Opening history does not also fetch the account table or render edit forms."""
    history = Mock()
    monkeypatch.setattr(users, "show_audit_history", history)
    ui.session_state["show_user_audit"] = True
    users.show_user_management()
    history.assert_called_once_with()
    api.assert_not_called()


@pytest.mark.parametrize("clear", [False, True])
def test_search_changes_reset_pagination_and_selection(ui, clear):
    """Avoid stale page offsets or selected accounts after changing the query."""
    ui.session_state.update(
        users_search="Taylor", users_offset=25, managed_user_id="old"
    )
    if clear:
        users._clear_user_search()
    else:
        users._reset_user_search()
    assert ui.session_state["users_offset"] == 0
    assert "managed_user_id" not in ui.session_state
    assert ui.session_state["users_search"] == ("" if clear else "Taylor")


@pytest.mark.parametrize(
    "values, acknowledged, message",
    [
        (["", "Name"], True, "Enter a username and display name."),
        (
            ["renamed", "Name"],
            False,
            "Confirm that a username change signs out all sessions.",
        ),
    ],
)
def test_rename_requires_valid_names_and_username_acknowledgement(
    ui, api, values, acknowledged, message
):
    """Do not send an identity edit before confirming its session consequences."""
    ui.form_submit_button.return_value = True
    ui.text_input.side_effect = values
    ui.checkbox.return_value = acknowledged
    users._rename_account_form(ACCOUNT)
    api.assert_not_called()
    ui.error.assert_called_once_with(message)


def test_normalized_rename_noop_does_not_send_request(ui, api):
    """Case and whitespace alone must not revoke the user's sessions."""
    ui.form_submit_button.return_value = True
    ui.text_input.side_effect = [" OTHER ", " Other User "]
    users._rename_account_form(ACCOUNT)
    api.assert_not_called()
    ui.info.assert_called_once_with("No account details changed.")


@pytest.mark.parametrize("succeeds", [False, True])
def test_display_rename_submits_only_changed_field_without_revocation_ack(
    ui, api, succeeds
):
    """A display-only edit does not submit or unintentionally restore a username."""
    ui.form_submit_button.return_value = True
    ui.text_input.side_effect = ["other", "New Display"]
    ui.checkbox.return_value = False
    api.return_value = {**ACCOUNT, "display_name": "New Display"} if succeeds else None
    if succeeds:
        with pytest.raises(RerunRequested):
            users._rename_account_form(ACCOUNT)
    else:
        users._rename_account_form(ACCOUNT)
        assert "user_management_notice" not in ui.session_state
    api.assert_called_once_with(
        "PATCH", "/users/other-id/profile", payload={"display_name": "New Display"}
    )


@pytest.mark.parametrize("username_changed", [False, True])
def test_self_rename_clears_session_only_for_username_changes(
    ui, api, monkeypatch, username_changed
):
    """Display changes refresh identity; changing login name returns the admin to login."""
    monkeypatch.setattr(auth_state, "st", ui)
    current = {**ACCOUNT, "user_id": "admin-id", "role": "admin"}
    new_username = "renamed-admin" if username_changed else current["username"]
    ui.session_state.update(auth_token="old-token", report={"notes": "Saved notes."})
    ui.form_submit_button.return_value = True
    ui.text_input.side_effect = [new_username, "New Admin Name"]
    updated = {**current, "username": new_username, "display_name": "New Admin Name"}
    api.return_value = updated
    with pytest.raises(RerunRequested):
        users._rename_account_form(current)
    if username_changed:
        assert set(ui.session_state) == {"auth_notice"}
    else:
        assert ui.session_state["auth_user"] == updated
        assert ui.session_state["auth_token"] == "old-token"
        assert ui.session_state["report"] == {"notes": "Saved notes."}


@pytest.mark.parametrize(
    "acknowledged, passwords, message",
    [
        (
            False,
            [PASSWORD, PASSWORD],
            "Confirm that you understand all sessions will be signed out.",
        ),
        (True, [PASSWORD, "Different"], "Passwords do not match."),
        (
            True,
            ["short", "short"],
            "New account passwords must contain 15 to 1024 characters.",
        ),
    ],
)
def test_reset_validates_confirmation(ui, api, acknowledged, passwords, message):
    """Require acknowledgement and matching policy-compliant passwords before sending."""
    ui.form_submit_button.return_value = True
    ui.checkbox.return_value = acknowledged
    ui.text_input.side_effect = passwords
    ui.session_state["reset_password_other-id"] = PASSWORD
    users._password_reset_form(ACCOUNT)
    api.assert_not_called()
    ui.error.assert_called_once_with(message)
    assert "reset_password_other-id" not in ui.session_state


@pytest.mark.parametrize("succeeds", [False, True])
def test_reset_submits_once_without_retaining_password(ui, api, succeeds):
    """Failed requests do not show a success notice or retain a replacement password."""
    ui.form_submit_button.return_value = True
    ui.text_input.side_effect = [PASSWORD, PASSWORD]
    api.return_value = ACCOUNT if succeeds else None
    ui.session_state["reset_password_other-id"] = PASSWORD
    ui.session_state["reset_password_confirmation_other-id"] = PASSWORD
    if succeeds:
        with pytest.raises(RerunRequested):
            users._password_reset_form(ACCOUNT)
    else:
        users._password_reset_form(ACCOUNT)
        assert "user_management_notice" not in ui.session_state
    api.assert_called_once_with(
        "POST", "/users/other-id/reset-password", payload={"password": PASSWORD}
    )
    assert "reset_password_other-id" not in ui.session_state
    assert "reset_password_confirmation_other-id" not in ui.session_state
