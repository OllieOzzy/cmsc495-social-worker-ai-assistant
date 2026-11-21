"""Verify report access boundaries with real login sessions and SQLite storage."""

from functools import cache
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from documentation_assistant.backend.api import reports
from documentation_assistant.backend.auth.passwords import hash_password
from documentation_assistant.backend.db import (
    delete_draft,
    edit_draft,
    get_draft,
    save_draft,
)
from documentation_assistant.backend.db.connection import connect
from documentation_assistant.backend.db.users import create_user
from documentation_assistant.backend.main import create_app
from documentation_assistant.backend.schemas.reports import (
    DAPSections,
    EditReportRequest,
)

_PASSWORD = "Synthetic permissions test password!"
_SECTIONS = {
    "data": "Synthetic data.",
    "assessment": "Progress observed.",
    "plan": "Follow up.",
}


@cache
def password_hash():
    """Reuse the synthetic hash while still testing real credential verification."""
    return hash_password(_PASSWORD)


@pytest.fixture
def access(monkeypatch, tmp_path):
    """Sign in two regular accounts and an admin without overriding auth dependencies."""
    path = tmp_path / "permissions.db"
    monkeypatch.setenv("DAP_DB_PATH", str(path))
    inference = AsyncMock(return_value=DAPSections(**_SECTIONS))
    monkeypatch.setattr(reports, "generate_dap", inference)
    with TestClient(create_app()) as client:
        users, headers = {}, {}
        for name, role in (("alice", "user"), ("bobby", "user"), ("admin", "admin")):
            users[name] = create_user(
                path,
                username=name,
                display_name=name.title(),
                password_hash=password_hash(),
                role=role,
            )
            signed_in = client.post(
                "/auth/login", json={"username": name, "password": _PASSWORD}
            )
            assert signed_in.status_code == 200
            headers[name] = {
                "Authorization": f"Bearer {signed_in.json()['access_token']}"
            }
        created = client.post(
            "/reports/manual",
            json={"notes": "Original notes."},
            headers=headers["alice"],
        )
        assert created.status_code == 201
        url = f"/reports/{created.json()['report_id']}"
        saved = client.patch(
            url, json={"revision": 1, "sections": _SECTIONS}, headers=headers["alice"]
        )
        assert saved.status_code == 200
        yield SimpleNamespace(
            client=client,
            path=path,
            users=users,
            headers=headers,
            url=url,
            report=saved.json(),
            inference=inference,
        )


@pytest.mark.parametrize(
    "method, suffix, body",
    [
        ("GET", "", None),
        ("GET", "/download", None),
        ("PATCH", "", {"revision": 2, "notes": "Changed."}),
        ("DELETE", "?revision=2", None),
        ("POST", "/regenerate", {"revision": 2, "notes": "Changed."}),
        ("POST", "/approve", {"revision": 2}),
        ("POST", "/reopen", {"revision": 2}),
    ],
)
def test_every_saved_report_action_requires_login(access, method, suffix, body):
    """No report ID, PDF, or write action grants access without a live token."""
    response = access.client.request(method, access.url + suffix, json=body)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    access.inference.assert_not_awaited()
    assert (
        access.client.get(access.url, headers=access.headers["alice"]).json()
        == access.report
    )


@pytest.mark.parametrize(
    "method, route, body",
    [
        ("GET", "/reports", None),
        ("POST", "/reports/manual", {}),
        ("POST", "/reports/generate", {"notes": "Synthetic notes."}),
    ],
)
def test_listing_and_creation_require_login(access, method, route, body):
    """Unauthenticated creation must not invoke the model or save a draft."""
    assert access.client.request(method, route, json=body).status_code == 401
    access.inference.assert_not_awaited()
    with connect(access.path) as connection:
        assert (
            connection.execute("SELECT count(*) FROM report_drafts").fetchone()[0] == 1
        )


@pytest.mark.parametrize(
    "viewer, status", [("alice", 200), ("bobby", 404), ("admin", 200)]
)
@pytest.mark.parametrize("suffix", ["", "/download"])
def test_read_and_pdf_access_follow_ownership(access, viewer, status, suffix):
    """Admins can review any report; other users cannot discover or export it."""
    response = access.client.get(access.url + suffix, headers=access.headers[viewer])
    assert response.status_code == status
    if status == 404:
        assert response.json() == {"detail": "Report draft not found."}


def test_history_is_scoped_and_creation_uses_signed_in_identity(access):
    """User input cannot select an owner; admin history includes unassigned rows."""
    other = access.client.post(
        "/reports/generate",
        json={"notes": "Other notes."},
        headers=access.headers["bobby"],
    )
    assert other.status_code == 200
    other_id = other.json()["report_id"]
    other_saved = access.client.get(
        f"/reports/{other_id}", headers=access.headers["bobby"]
    ).json()
    assert other_saved["owner_id"] == str(access.users["bobby"].user_id)
    assert access.report["owner_id"] == str(access.users["alice"].user_id)
    legacy = save_draft(access.path, "Legacy.", DAPSections(**_SECTIONS))
    for name in ("alice", "bobby", "admin"):
        listing = access.client.get("/reports", headers=access.headers[name]).json()
        expected = (
            {access.report["report_id"]}
            if name == "alice"
            else {other_id}
            if name == "bobby"
            else {access.report["report_id"], other_id, str(legacy.report_id)}
        )
        assert {row["report_id"] for row in listing} == expected
    assert (
        access.client.get(
            f"/reports/{legacy.report_id}", headers=access.headers["alice"]
        ).status_code
        == 404
    )
    forged = access.client.post(
        "/reports/manual",
        json={"owner_id": str(access.users["bobby"].user_id)},
        headers=access.headers["alice"],
    )
    assert forged.status_code == 422


@pytest.mark.parametrize("viewer, status", [("bobby", 404), ("admin", 403)])
@pytest.mark.parametrize(
    "method, suffix, body",
    [
        ("PATCH", "", {"revision": 2, "notes": "Unwanted change."}),
        ("DELETE", "?revision=2", None),
        ("POST", "/regenerate", {"revision": 2, "notes": "Unwanted change."}),
    ],
)
def test_only_owner_can_change_or_delete_content(
    access, viewer, status, method, suffix, body
):
    """Administrative review access does not grant permission to rewrite others' notes."""
    response = access.client.request(
        method, access.url + suffix, json=body, headers=access.headers[viewer]
    )
    assert response.status_code == status
    access.inference.assert_not_awaited()
    assert (
        access.client.get(access.url, headers=access.headers["alice"]).json()
        == access.report
    )


@pytest.mark.parametrize("suffix", ["/approve", "/reopen"])
@pytest.mark.parametrize("viewer", ["alice", "bobby"])
def test_regular_users_cannot_approve_or_reopen_any_report(access, suffix, viewer):
    """The admin dependency denies review actions before exposing report state."""
    for url in (access.url, f"/reports/{uuid4()}"):
        response = access.client.post(
            url + suffix, json={"revision": 2}, headers=access.headers[viewer]
        )
        assert response.status_code == 403


def test_admin_approval_records_authenticated_identity_and_owner_can_read_export(
    access,
):
    """Ignore forged reviewer names; approval is attributable to a stable admin ID."""
    response = access.client.post(
        access.url + "/approve",
        json={"revision": 2, "approved_by": "Forged Reviewer"},
        headers=access.headers["admin"],
    )
    assert response.status_code == 200
    approved = response.json()
    assert approved["approved_by"] == "Admin"
    with connect(access.path) as connection:
        assert connection.execute(
            "SELECT approved_by_id FROM report_drafts"
        ).fetchone()[0] == str(access.users["admin"].user_id)
    owner_headers = access.headers["alice"]
    assert access.client.get(access.url, headers=owner_headers).json() == approved
    assert (
        access.client.get(access.url + "/download", headers=owner_headers).status_code
        == 200
    )
    assert (
        access.client.patch(
            access.url, json={"revision": 3, "notes": "Changed."}, headers=owner_headers
        ).status_code
        == 409
    )
    assert (
        access.client.delete(
            access.url + "?revision=3", headers=owner_headers
        ).status_code
        == 409
    )
    reopened = access.client.post(
        access.url + "/reopen", json={"revision": 3}, headers=access.headers["admin"]
    )
    assert reopened.status_code == 200
    assert reopened.json()["owner_id"] == approved["owner_id"]
    with connect(access.path) as connection:
        assert (
            connection.execute("SELECT approved_by_id FROM report_drafts").fetchone()[0]
            is None
        )
    assert (
        access.client.patch(
            access.url,
            json={"revision": 4, "notes": "Corrected."},
            headers=owner_headers,
        ).status_code
        == 200
    )


def test_admin_cannot_delete_own_approved_report(access):
    """Approved-report deletion protection applies to administrators too."""
    created = access.client.post(
        "/reports/manual", json={}, headers=access.headers["admin"]
    ).json()
    url = f"/reports/{created['report_id']}"
    access.client.patch(
        url,
        json={"revision": 1, "sections": _SECTIONS},
        headers=access.headers["admin"],
    ).raise_for_status()
    access.client.post(
        url + "/approve", json={"revision": 2}, headers=access.headers["admin"]
    ).raise_for_status()
    assert (
        access.client.delete(
            url + "?revision=3", headers=access.headers["admin"]
        ).status_code
        == 409
    )


def test_owner_is_rechecked_when_regeneration_finishes(access):
    """The final write cannot alter a report transferred during a long model call."""

    async def transfer_during_inference(*args):
        """Simulate a maintenance ownership change while generation is in progress."""
        with connect(access.path) as connection:
            connection.execute(
                "UPDATE report_drafts SET owner_id = ?",
                (str(access.users["bobby"].user_id),),
            )
        return DAPSections(**_SECTIONS)

    access.inference.side_effect = transfer_during_inference
    response = access.client.post(
        access.url + "/regenerate",
        json={"revision": 2, "notes": "Replacement notes."},
        headers=access.headers["alice"],
    )
    assert response.status_code == 404
    saved = access.client.get(access.url, headers=access.headers["bobby"]).json()
    assert saved["notes"] == "Original notes."
    assert saved["revision"] == 2


def test_storage_owner_checks_prevent_writes_even_without_api_precheck(access):
    """Database mutation guards reject another owner without leaking report state."""
    other_owner_id = access.users["bobby"].user_id
    # The supplied owner is Bobby; the report actually belongs to Alice.
    from uuid import UUID

    saved_id = UUID(access.report["report_id"])
    assert (
        edit_draft(
            access.path,
            saved_id,
            EditReportRequest(revision=2, notes="Changed."),
            owner_id=other_owner_id,
        )
        is None
    )
    assert not delete_draft(access.path, saved_id, 2, owner_id=other_owner_id)
    assert get_draft(access.path, saved_id).notes == "Original notes."


def test_revoked_token_cannot_access_reports(access):
    """Report endpoints consult live session storage, not stale client identity."""
    headers = access.headers["alice"]
    access.client.post("/auth/logout", headers=headers).raise_for_status()
    assert access.client.get(access.url, headers=headers).status_code == 401
    assert access.client.get("/reports", headers=headers).status_code == 401


def test_report_json_responses_cannot_be_cached(access):
    """History, saved notes, and write responses carry the same protection as PDFs."""
    headers = access.headers["alice"]
    responses = [
        access.client.get("/reports", headers=headers),
        access.client.get(access.url, headers=headers),
        access.client.post("/reports/manual", json={}, headers=headers),
        access.client.patch(
            access.url, json={"revision": 2, "notes": "Updated."}, headers=headers
        ),
    ]
    for response in responses:
        assert response.is_success, response.text
        assert response.headers["cache-control"] == "no-store"
