"""Verify read-only history rendering, permissions, and bounded pagination."""

from unittest.mock import MagicMock, Mock

import pytest

from documentation_assistant.frontend import audit

EVENT = {
    "event_id": 1,
    "occurred_at": "2026-11-21T12:00:00Z",
    "actor_id": None,
    "actor_username": None,
    "target_id": "target-id",
    "target_username": "target",
    "action": "role_changed",
    "changes": {"role": {"before": "user", "after": "admin"}},
}


class RerunRequested(Exception):
    """Stop where Streamlit would rerun the application."""


@pytest.fixture
def ui(monkeypatch):
    """Mock only Streamlit widgets, leaving request construction observable."""
    view = MagicMock()
    view.session_state = {}
    view.button.return_value = False
    view.rerun.side_effect = RerunRequested
    monkeypatch.setattr(audit, "st", view)
    monkeypatch.setattr(audit, "is_admin", lambda: True)
    return view


@pytest.fixture
def api(monkeypatch):
    """Avoid any network access while checking the request contract."""
    request = Mock(return_value=[EVENT])
    monkeypatch.setattr(audit, "request_api", request)
    return request


def test_history_blocks_regular_users(ui, api, monkeypatch):
    """Direct renderer calls still enforce administrator access."""
    monkeypatch.setattr(audit, "is_admin", lambda: False)
    audit.show_audit_history()
    api.assert_not_called()
    ui.error.assert_called_once_with("Administrator access required.")


def test_history_renders_public_changes_and_local_attribution(ui, api):
    """Human-readable rows preserve IDs and make unauthenticated local actions explicit."""
    audit.show_audit_history()
    api.assert_called_once_with(
        "GET", "/users/audit-events", params={"limit": 26, "offset": 0}
    )
    row = ui.dataframe.call_args.args[0][0]
    assert row["Actor"] == "Local operation"
    assert row["Account ID"] == "target-id"
    assert row["Changes"] == "role: user → admin"


def test_authentication_attempt_has_no_fabricated_actor_or_account_id(ui, api):
    """Unknown usernames display without claiming a local operation or account owner."""
    api.return_value = [
        {**EVENT, "action": "login_failed", "target_id": None, "changes": {}}
    ]
    audit.show_audit_history()
    row = ui.dataframe.call_args.args[0][0]
    assert row["Actor"] == "Authentication attempt"
    assert row["Account ID"] == ""
    assert row["Action"] == "login failed"


@pytest.mark.parametrize("response", [None, []])
def test_empty_and_failed_history_requests_remain_recoverable(ui, api, response):
    """A failed request does not render stale history; empty pages get a message."""
    api.return_value = response
    audit.show_audit_history()
    ui.dataframe.assert_not_called()
    assert ui.info.called == (response == [])
    assert any(call.args[0] == "Refresh history" for call in ui.button.call_args_list)


@pytest.mark.parametrize(
    "label, offset, expected",
    [("Next events", 0, 25), ("Previous events", 25, 0), ("Refresh history", 25, 0)],
)
def test_history_navigation_stays_bounded(ui, api, label, offset, expected):
    """Fetch a sentinel row and preserve page offsets, with refresh returning to the newest."""
    ui.session_state["audit_offset"] = offset
    ui.button.side_effect = lambda text, **kwargs: text == label and not kwargs.get(
        "disabled", False
    )
    api.return_value = [EVENT] * 26
    with pytest.raises(RerunRequested):
        audit.show_audit_history()
    assert ui.session_state["audit_offset"] == expected
    if label == "Refresh history":
        api.assert_not_called()
    else:
        assert len(ui.dataframe.call_args.args[0]) == 25
