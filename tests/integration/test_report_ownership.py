"""Verify report ownership and scoped reads against isolated SQLite databases.

These storage tests prepare the API permission work. They do not imply the
report routes require authentication before that separate step is applied.
"""

import sqlite3
from uuid import uuid4

import pytest

from documentation_assistant.backend.db import (
    approve_draft,
    assign_report_owner,
    edit_draft,
    get_draft,
    list_drafts,
    reopen_approved_report,
    save_draft,
)
from documentation_assistant.backend.db.connection import connect, initialize_database
from documentation_assistant.backend.db.users import create_user
from documentation_assistant.backend.schemas.reports import (
    DraftSections,
    EditReportRequest,
    ReportFilters,
    ReportMetadata,
)

SECTIONS = DraftSections(
    data="Synthetic data.", assessment="No change.", plan="Follow up."
)


@pytest.fixture
def accounts(tmp_path):
    """Create two regular users and one administrator without touching app data."""
    path = tmp_path / "ownership.db"
    initialize_database(path)
    identities = [
        create_user(
            path,
            username=name,
            display_name=name.title(),
            password_hash="synthetic-encoded-hash",
            role=role,
        )
        for name, role in (("alice", "user"), ("bobby", "user"), ("admin", "admin"))
    ]
    return path, *identities


def test_regular_users_only_read_their_own_reports_and_admin_reads_all(accounts):
    """Inaccessible IDs look missing, and unassigned reports are admin-visible."""
    path, alice, bobby, admin = accounts
    first = save_draft(path, "Alice notes.", SECTIONS, owner_id=alice.user_id)
    second = save_draft(path, "Bobby notes.", SECTIONS, owner_id=bobby.user_id)
    legacy = save_draft(path, "Unassigned notes.", SECTIONS)

    assert get_draft(path, first.report_id, viewer=alice) == first
    assert get_draft(path, first.report_id, viewer=bobby) is None
    assert get_draft(path, second.report_id, viewer=alice) is None
    assert get_draft(path, legacy.report_id, viewer=alice) is None
    assert get_draft(path, uuid4(), viewer=alice) is None
    assert [row.report_id for row in list_drafts(path, viewer=alice)] == [
        first.report_id
    ]
    assert [row.report_id for row in list_drafts(path, viewer=bobby)] == [
        second.report_id
    ]
    assert [row.report_id for row in list_drafts(path, viewer=admin)] == [
        legacy.report_id,
        second.report_id,
        first.report_id,
    ]
    for report in (first, second, legacy):
        assert get_draft(path, report.report_id, viewer=admin) == report
    assert [row.owner_id for row in list_drafts(path, viewer=admin)] == [
        None,
        bobby.user_id,
        alice.user_id,
    ]


def test_ownership_and_search_are_applied_before_pagination(accounts):
    """Other users' matches must not displace the current user's paginated rows."""
    path, alice, bobby, _ = accounts
    own = []
    for index in range(3):
        own.append(
            save_draft(
                path,
                f"Own report {index}.",
                SECTIONS,
                ReportMetadata(school="Example School"),
                owner_id=alice.user_id,
            )
        )
        save_draft(
            path,
            "Other user.",
            SECTIONS,
            ReportMetadata(school="Example School"),
            owner_id=bobby.user_id,
        )
    save_draft(path, "Different school.", SECTIONS, owner_id=alice.user_id)
    filters = ReportFilters(school="example school", limit=1, offset=1)
    assert [row.report_id for row in list_drafts(path, filters, viewer=alice)] == [
        own[1].report_id
    ]
    assert (
        list_drafts(
            path,
            ReportFilters(school="Example School", offset=3),
            viewer=alice,
        )
        == []
    )


def test_report_workflow_preserves_the_original_owner(accounts):
    """Editing, approval, and reopening cannot accidentally transfer ownership."""
    path, alice, _, _ = accounts
    report = save_draft(path, "Original.", SECTIONS, owner_id=alice.user_id)
    edited = edit_draft(
        path,
        report.report_id,
        EditReportRequest(revision=1, notes="Corrected."),
    )
    approved = approve_draft(path, report.report_id, edited.revision, "Administrator")
    reopened = reopen_approved_report(path, report.report_id, approved.revision)
    assert edited.owner_id == approved.owner_id == reopened.owner_id == alice.user_id
    assert get_draft(path, report.report_id, viewer=alice) == reopened


def test_explicit_assignment_preserves_content_and_never_transfers_owned_reports(
    accounts,
):
    """A maintenance action assigns only NULL owners, without changing revisions."""
    path, alice, bobby, _ = accounts
    report = save_draft(path, "Existing notes.", SECTIONS)
    assert assign_report_owner(path, report.report_id, alice.user_id)
    saved = get_draft(path, report.report_id, viewer=alice)
    assert saved.model_dump(exclude={"owner_id"}) == report.model_dump(
        exclude={"owner_id"}
    )
    assert not assign_report_owner(path, report.report_id, bobby.user_id)
    assert not assign_report_owner(path, uuid4(), alice.user_id)
    assert get_draft(path, report.report_id, viewer=bobby) is None
    assert get_draft(path, report.report_id).owner_id == alice.user_id


@pytest.mark.parametrize("operation", ["create", "assign"])
def test_unknown_owner_is_rejected_by_foreign_key(accounts, operation):
    """Ownership cannot reference an account that does not exist."""
    path, _, _, _ = accounts
    report = save_draft(path, "Unassigned.", SECTIONS)
    with pytest.raises(sqlite3.IntegrityError):
        if operation == "create":
            save_draft(path, "Invalid owner.", SECTIONS, owner_id=uuid4())
        else:
            assign_report_owner(path, report.report_id, uuid4())
    assert get_draft(path, report.report_id).owner_id is None
    assert len(list_drafts(path)) == 1


def test_account_deletion_does_not_orphan_its_reports(accounts):
    """Accounts owning reports cannot be deleted through a direct SQLite write."""
    path, alice, _, _ = accounts
    report = save_draft(path, "Owned notes.", SECTIONS, owner_id=alice.user_id)
    with pytest.raises(sqlite3.IntegrityError), connect(path) as connection:
        connection.execute("DELETE FROM users WHERE user_id = ?", (str(alice.user_id),))
    assert get_draft(path, report.report_id, viewer=alice) == report


def test_upgrade_leaves_legacy_reports_unassigned_until_explicit_assignment(tmp_path):
    """A real pre-authentication schema upgrades without assigning existing notes."""
    path = tmp_path / "legacy.db"
    report_id = uuid4()
    with sqlite3.connect(path) as connection:
        connection.execute("""CREATE TABLE report_drafts (
            report_id TEXT PRIMARY KEY, notes TEXT NOT NULL, data TEXT NOT NULL,
            assessment TEXT NOT NULL, plan TEXT NOT NULL)""")
        connection.execute(
            "INSERT INTO report_drafts VALUES (?, ?, ?, ?, ?)",
            (str(report_id), "Legacy notes.", "Data.", "Assessment.", "Plan."),
        )
    initialize_database(path)
    regular = create_user(
        path,
        username="user",
        display_name="User",
        password_hash="synthetic-hash",
    )
    admin = create_user(
        path,
        username="admin",
        display_name="Admin",
        password_hash="synthetic-hash",
        role="admin",
    )
    initialize_database(path)
    assert list_drafts(path, viewer=regular) == []
    assert get_draft(path, report_id, viewer=regular) is None
    legacy = get_draft(path, report_id, viewer=admin)
    assert legacy.notes == "Legacy notes."
    assert legacy.owner_id is None
    assert len(list_drafts(path, viewer=admin)) == 1
    assert assign_report_owner(path, report_id, regular.user_id)
    assert get_draft(path, report_id, viewer=regular).notes == legacy.notes


@pytest.mark.parametrize(
    "payload",
    [
        {"owner_id": str(uuid4())},
        {"notes": "Forged owner.", "owner_id": str(uuid4())},
    ],
)
def test_ownership_is_not_a_client_editable_request_field(payload):
    """Only server-side creation and explicit maintenance may set report owners."""
    from pydantic import ValidationError

    from documentation_assistant.backend.schemas.reports import ManualReportRequest

    with pytest.raises(ValidationError):
        ManualReportRequest.model_validate(payload)
    with pytest.raises(ValidationError):
        EditReportRequest.model_validate({"revision": 1, **payload})
