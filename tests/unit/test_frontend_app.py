"""Verify app entry-point routing with isolated Streamlit and report handlers."""

import runpy
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from documentation_assistant.frontend import auth, reports, sidebar, users

APP_PATH = Path(reports.__file__).with_name("app.py")


class RenderStopped(Exception):
    """Simulate Streamlit ending the current render."""


@pytest.fixture
def app(monkeypatch):
    """Replace screen handlers so each test covers only app routing."""
    streamlit = MagicMock()
    streamlit.context.url = "http://localhost:8501"
    streamlit.session_state = {}
    streamlit.query_params = {}
    streamlit.button.return_value = False
    streamlit.stop.side_effect = RenderStopped
    streamlit.rerun.side_effect = RenderStopped
    # run_path executes the entry point again, so replace its streamlit import
    # as well as the report handlers it imports from already-loaded modules.
    monkeypatch.setitem(sys.modules, "streamlit", streamlit)
    handlers = {}
    for name in ("new_report", "open_report", "review_report"):
        handlers[name] = Mock()
        monkeypatch.setattr(reports, name, handlers[name])
    handlers["show_sidebar"] = Mock()
    monkeypatch.setattr(sidebar, "show_sidebar", handlers["show_sidebar"])
    handlers["require_login"] = Mock(return_value=True)
    monkeypatch.setattr(auth, "require_login", handlers["require_login"])
    handlers["show_admin_navigation"] = Mock(return_value=False)
    handlers["show_user_management"] = Mock()
    monkeypatch.setattr(
        users, "show_admin_navigation", handlers["show_admin_navigation"]
    )
    monkeypatch.setattr(users, "show_user_management", handlers["show_user_management"])
    return SimpleNamespace(ui=streamlit, **handlers)


def test_default_view_routes_to_new_report(app):
    """A session without a selected report opens the new report screen."""
    runpy.run_path(str(APP_PATH))

    app.show_sidebar.assert_called_once_with()
    app.new_report.assert_called_once_with()
    app.review_report.assert_not_called()
    app.open_report.assert_not_called()


def test_user_management_routes_without_rendering_report_content(app):
    """The management screen and report screens do not share the same render."""
    app.show_admin_navigation.return_value = True
    with pytest.raises(RenderStopped):
        runpy.run_path(str(APP_PATH))
    app.show_user_management.assert_called_once_with()
    app.show_sidebar.assert_not_called()
    app.review_report.assert_not_called()


def test_unauthenticated_view_does_not_render_reports_or_history(app):
    """A cached report must never render while the login gate is closed."""
    app.require_login.return_value = False
    app.ui.session_state["report"] = {"notes": "Private cached notes."}
    with pytest.raises(RenderStopped):
        runpy.run_path(str(APP_PATH))
    app.show_sidebar.assert_not_called()
    app.review_report.assert_not_called()
    app.new_report.assert_not_called()


def test_saved_report_routes_to_review_before_pending_recovery(app):
    """An opened report takes precedence over a leftover pending report ID."""
    report = {"report_id": "saved-report"}
    app.ui.session_state.update(report=report, pending_report_id="pending-report")

    runpy.run_path(str(APP_PATH))

    app.review_report.assert_called_once_with(report)
    app.new_report.assert_not_called()
    app.open_report.assert_not_called()


@pytest.mark.parametrize("retry", [False, True])
def test_pending_draft_waits_for_retry_and_reuses_saved_id(app, retry):
    """Present recovery without routing back to a new report."""
    app.ui.session_state["pending_report_id"] = "saved-report"
    app.ui.button.return_value = retry

    runpy.run_path(str(APP_PATH))

    app.ui.warning.assert_called_once_with(
        "Your draft was saved, but it could not be opened."
    )
    app.ui.button.assert_called_once_with(
        "Retry opening draft", key="retry_opening_draft"
    )
    if retry:
        app.open_report.assert_called_once_with("saved-report")
    else:
        app.open_report.assert_not_called()
    app.new_report.assert_not_called()
    app.review_report.assert_not_called()


def test_report_notice_is_displayed_once(app):
    """Consume a saved action notice so later reruns do not show it again."""
    app.ui.session_state["report_notice"] = "Draft saved."

    runpy.run_path(str(APP_PATH))
    runpy.run_path(str(APP_PATH))

    app.ui.success.assert_called_once_with("Draft saved.")
    assert "report_notice" not in app.ui.session_state


def test_absent_notice_does_not_show_success_message(app):
    """Opening the app does not invent a successful action notification."""
    runpy.run_path(str(APP_PATH))

    app.ui.success.assert_not_called()


@pytest.mark.parametrize(
    "url",
    ["http://localhost:8501", "https://example.test/dap/?old=value#section"],
)
def test_contacts_menu_uses_current_app_address(app, url):
    """Keep the contacts URL on the app's host and deployment path."""
    app.ui.context.url = url

    runpy.run_path(str(APP_PATH))

    config = app.ui.set_page_config.call_args.kwargs
    expected = (
        "http://localhost:8501?view=contacts"
        if url.startswith("http://localhost")
        else "https://example.test/dap/?view=contacts"
    )
    assert config["menu_items"]["Report a bug"] == expected
    assert "DAP Documentation Assistant" in config["menu_items"]["About"]


def test_menu_handles_missing_app_url(app):
    """Configure the app when Streamlit has no browser URL available."""
    app.ui.context.url = None

    runpy.run_path(str(APP_PATH))

    assert "About" in app.ui.set_page_config.call_args.kwargs["menu_items"]
    assert "Report a bug" not in app.ui.set_page_config.call_args.kwargs["menu_items"]


def test_contacts_view_stops_before_report_navigation(app):
    """Show team contacts without opening report screens or their sidebar."""
    app.ui.query_params["view"] = "contacts"

    with pytest.raises(RenderStopped):
        runpy.run_path(str(APP_PATH))

    app.ui.title.assert_called_once_with("Contacts")
    app.show_sidebar.assert_not_called()
    app.new_report.assert_not_called()
    app.review_report.assert_not_called()


def test_back_to_reports_clears_contacts_query_and_reruns(app):
    """Return from contacts while preserving other URL parameters and report state."""
    app.ui.query_params.update(view="contacts", other="keep")
    app.ui.session_state["report"] = {"report_id": "example"}
    app.ui.button.return_value = True

    with pytest.raises(RenderStopped):
        runpy.run_path(str(APP_PATH))

    assert app.ui.query_params == {"other": "keep"}
    assert app.ui.session_state["report"] == {"report_id": "example"}
    app.ui.rerun.assert_called_once_with()
    app.ui.stop.assert_not_called()
