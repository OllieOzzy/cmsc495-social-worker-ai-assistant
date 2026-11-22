"""Reject pending AI writes when their initiating session is no longer valid."""

import pytest

from documentation_assistant.backend.api import reports
from documentation_assistant.backend.auth.service import logout
from documentation_assistant.backend.db import get_draft, sessions
from documentation_assistant.backend.db.connection import connect
from documentation_assistant.backend.db.users import (
    rename_user,
    reset_user_password,
    set_user_active,
    set_user_role,
)
from documentation_assistant.backend.schemas.reports import DAPSections
from tests.integration.test_user_management_api import accounts as _management_accounts
from tests.integration.test_user_management_api import encoded_password

accounts = _management_accounts
SECTIONS = DAPSections(
    data="Synthetic data.", assessment="Synthetic assessment.", plan="Synthetic plan."
)


def invalidate(accounts, monkeypatch, reason):
    """Apply real revocation operations; expiry advances only the write guard's clock."""
    user_id = accounts.identities["user"].user_id
    if reason == "logout":
        logout(accounts.path, accounts.headers["user"]["Authorization"].split()[1])
    elif reason == "deactivate":
        set_user_active(accounts.path, user_id, is_active=False)
    elif reason == "password_reset":
        reset_user_password(accounts.path, user_id, password_hash=encoded_password())
    elif reason == "rename":
        rename_user(accounts.path, user_id, username="renamed-user")
    elif reason == "role_change":
        set_user_role(accounts.path, user_id, role="admin")
    else:
        with connect(accounts.path) as connection:
            expiry = connection.execute(
                "SELECT expires_at FROM user_sessions WHERE user_id = ?",
                (str(user_id),),
            ).fetchone()[0]
        monkeypatch.setattr(sessions, "time", lambda: expiry)


@pytest.mark.parametrize("operation", ["generate", "regenerate"])
@pytest.mark.parametrize(
    "reason",
    ["logout", "deactivate", "password_reset", "rename", "role_change", "expiry"],
)
def test_revocation_during_inference_never_commits_report(
    accounts, monkeypatch, operation, reason
):
    """Return 401 and preserve the database instead of saving output from a stale session."""
    original = None
    payload = {"notes": "Synthetic updated notes."}
    route = "/reports/generate"
    if operation == "regenerate":
        saved = accounts.client.post(
            "/reports/manual",
            json={"notes": "Original notes."},
            headers=accounts.headers["user"],
        ).json()
        original = get_draft(accounts.path, saved["report_id"])
        route = f"/reports/{saved['report_id']}/regenerate"
        payload["revision"] = saved["revision"]

    async def infer_then_revoke(notes, client):
        """Complete structured AI output after the initiating session has changed."""
        invalidate(accounts, monkeypatch, reason)
        return SECTIONS

    monkeypatch.setattr(reports, "_generate_sections", infer_then_revoke)
    response = accounts.client.post(
        route, json=payload, headers=accounts.headers["user"]
    )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["cache-control"] == "no-store"
    with connect(accounts.path) as connection:
        assert connection.execute("SELECT count(*) FROM report_drafts").fetchone()[
            0
        ] == (1 if original else 0)
    if original:
        assert get_draft(accounts.path, original.report_id) == original


@pytest.mark.parametrize("operation", ["generate", "regenerate"])
def test_revocation_just_before_storage_is_checked_inside_transaction(
    accounts, monkeypatch, operation
):
    """Close the smaller race between inference completion and the storage thread starting."""
    payload = {"notes": "Synthetic new notes."}
    route = "/reports/generate"
    original = None
    if operation == "regenerate":
        saved = accounts.client.post(
            "/reports/manual",
            json={"notes": "Original notes."},
            headers=accounts.headers["user"],
        ).json()
        original = get_draft(accounts.path, saved["report_id"])
        payload["revision"] = saved["revision"]
        route = f"/reports/{saved['report_id']}/regenerate"
    original_dispatch = reports.run_in_threadpool

    async def inference(notes, client):
        return SECTIONS

    async def dispatch_after_revocation(function, *args, **kwargs):
        """Revoke only when the report-writing function is about to execute."""
        if function in (reports.save_draft, reports.edit_draft):
            invalidate(accounts, monkeypatch, "logout")
        return await original_dispatch(function, *args, **kwargs)

    monkeypatch.setattr(reports, "_generate_sections", inference)
    monkeypatch.setattr(reports, "run_in_threadpool", dispatch_after_revocation)
    assert (
        accounts.client.post(
            route, json=payload, headers=accounts.headers["user"]
        ).status_code
        == 401
    )
    if original:
        assert get_draft(accounts.path, original.report_id) == original
    else:
        with connect(accounts.path) as connection:
            assert (
                connection.execute("SELECT count(*) FROM report_drafts").fetchone()[0]
                == 0
            )
