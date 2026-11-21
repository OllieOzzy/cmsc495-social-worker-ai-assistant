"""Store DAP reports, source notes, and the current approval state.

Bandit flags queries built from strings as possible SQL injection (B608).
The marked queries build their SQL from schema field names and fixed clauses.
User input, such as notes or search filters, is bound separately to SQLite's
``?`` placeholders so it cannot change the SQL statement. The B608 exceptions
are safe as long as the SQL fragments come from the code and user values stay
bound as parameters.
"""

import sqlite3
from pathlib import Path
from uuid import UUID, uuid4

from documentation_assistant.backend.db.connection import connect
from documentation_assistant.backend.schemas.auth import UserAccount
from documentation_assistant.backend.schemas.reports import (
    DraftSections,
    EditReportRequest,
    ReportFilters,
    ReportMetadata,
    ReportSummary,
    SavedReportMetadata,
    StoredReportDraft,
)

_METADATA_FIELDS = tuple(ReportMetadata.model_fields)
_METADATA_COLUMNS = ", ".join(_METADATA_FIELDS)
_METADATA_PLACEHOLDERS = ", ".join("?" for _ in _METADATA_FIELDS)


class ReviewConflict(Exception):
    """The report's revision, status, or contents prevent the requested action."""


def save_draft(
    path: Path,
    notes: str,
    sections: DraftSections,
    metadata: ReportMetadata | None = None,
    *,
    owner_id: UUID | None = None,
) -> StoredReportDraft:
    """Insert a draft owned by the supplied account and return it after commit.

    None preserves unassigned legacy/internal reports during the authentication
    rollout. Authenticated API creation must supply the signed-in account ID.
    """
    details = metadata.model_dump(mode="json") if metadata is not None else {}
    metadata_values = [details.get(field) for field in _METADATA_FIELDS]
    draft = StoredReportDraft(
        report_id=uuid4(),
        owner_id=owner_id,
        notes=notes,
        sections=sections,
        metadata=_read_metadata(metadata_values),
    )
    with connect(path) as connection:
        # Only schema column names and generated placeholders are interpolated.
        connection.execute(
            f"""
            INSERT INTO report_drafts
                (report_id, owner_id, notes, data, assessment, plan, created_at,
                 {_METADATA_COLUMNS})
            VALUES (?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                    {_METADATA_PLACEHOLDERS})
            """,  # nosec B608
            (
                str(draft.report_id),
                str(owner_id) if owner_id is not None else None,
                notes,
                sections.data,
                sections.assessment,
                sections.plan,
                *metadata_values,
            ),
        )
    return draft


def list_drafts(
    path: Path,
    filters: ReportFilters | None = None,
    *,
    viewer: UserAccount | None = None,
) -> list[ReportSummary]:
    """List a bounded page of matching summaries in reverse insertion order.

    SQLite applies filters before limit and offset, so only summaries on the
    requested page are loaded and validated. An exhausted page returns [].
    With a viewer, regular accounts see only their own rows; administrators see
    all rows, including unassigned reports. None is reserved for trusted internal
    callers during rollout, not a substitute for authenticating an API request.
    """
    values = (filters or ReportFilters()).model_dump(mode="json")
    clauses = []
    parameters = []
    if viewer is not None and viewer.role != "admin":
        clauses.append("owner_id = ?")
        parameters.append(str(viewer.user_id))
    for condition, value in (
        ("instr(casefold(student_name), ?) > 0", _casefold(values["student_name"])),
        ("student_id = ?", values["student_id"]),
        ("casefold(school) = ?", _casefold(values["school"])),
        ("casefold(grade) = ?", _casefold(values["grade"])),
        ("date_of_service >= ?", values["date_from"]),
        ("date_of_service <= ?", values["date_to"]),
        ("status = ?", values["status"]),
        ("instr(casefold(approved_by), ?) > 0", _casefold(values["approved_by"])),
        (
            "instr(casefold(social_worker_name), ?) > 0",
            _casefold(values["social_worker_name"]),
        ),
    ):
        if value is None:
            continue
        clauses.append(condition)
        parameters.append(value)

    # Only fixed SQL fragments go into the query. Filter values are bound separately.
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect(path) as connection:
        connection.create_function("casefold", 1, _casefold)
        rows = connection.execute(
            f"""
            SELECT report_id, owner_id, created_at, status, approved_by, {_METADATA_COLUMNS}
            FROM report_drafts {where} ORDER BY rowid DESC LIMIT ? OFFSET ?
            """,  # nosec B608
            [*parameters, values["limit"], values["offset"]],
        ).fetchall()
    return [
        ReportSummary.model_validate(
            {
                "report_id": report_id,
                "owner_id": owner_id,
                "created_at": created_at,
                "status": status,
                "approved_by": approved_by,
                "metadata": _read_metadata(details),
            }
        )
        for report_id, owner_id, created_at, status, approved_by, *details in rows
    ]


def get_draft(
    path: Path, report_id: UUID, *, viewer: UserAccount | None = None
) -> StoredReportDraft | None:
    """Return a visible report, or None for missing and inaccessible IDs alike.

    Pass an authenticated viewer for user-facing reads. Omitting it is reserved
    for trusted internal operations during the authentication rollout.
    """
    with connect(path) as connection:
        return _get_report(connection, report_id, viewer=viewer)


def assign_report_owner(path: Path, report_id: UUID, owner_id: UUID) -> bool:
    """Explicitly assign an unowned report without changing content or revision.

    This trusted maintenance operation never transfers an already owned report.
    The account must exist; SQLite enforces the foreign key. No automatic
    assignment occurs during startup or login.
    """
    with connect(path) as connection:
        updated = connection.execute(
            "UPDATE report_drafts SET owner_id = ? "
            "WHERE report_id = ? AND owner_id IS NULL",
            (str(owner_id), str(report_id)),
        )
    return updated.rowcount == 1


def delete_draft(
    path: Path, report_id: UUID, revision: int, *, owner_id: UUID | None = None
) -> bool:
    """Delete a draft at the supplied revision and return False if it is missing."""
    owner = str(owner_id) if owner_id is not None else None
    with connect(path) as connection:
        # Check the status and revision in the same statement that deletes the row.
        deleted = connection.execute(
            "DELETE FROM report_drafts "
            "WHERE report_id = ? AND revision = ? AND status = 'draft' "
            "AND (? IS NULL OR owner_id = ?)",
            (str(report_id), revision, owner, owner),
        )
        if deleted.rowcount == 1:
            return True

        saved = connection.execute(
            "SELECT status FROM report_drafts WHERE report_id = ? "
            "AND (? IS NULL OR owner_id = ?)",
            (str(report_id), owner, owner),
        ).fetchone()
        if saved is None:
            return False
        if saved[0] == "approved":
            raise ReviewConflict("Approved reports cannot be deleted.")
        raise ReviewConflict("Report changed. Reload the current revision.")


def edit_draft(
    path: Path,
    report_id: UUID,
    edit: EditReportRequest,
    *,
    ai_assisted: bool = False,
    owner_id: UUID | None = None,
) -> StoredReportDraft | None:
    """Apply changes to a draft and return its incremented revision."""
    changes = edit.sections.model_dump() if edit.sections is not None else {}
    if edit.notes is not None:
        changes["notes"] = edit.notes
    if edit.metadata is not None:
        # Omitted keys keep their saved values. Explicit nulls clear a field.
        changes.update(edit.metadata.model_dump(mode="json", exclude_unset=True))
    if ai_assisted:
        changes["draft_source"] = "ai_assisted"

    # Column names come from the schemas. Bind user-entered values separately.
    return _update_review(
        path,
        report_id,
        edit.revision,
        ", ".join(f"{column} = ?" for column in changes),
        tuple(changes.values()),
        check_time_range="start_time" in changes or "end_time" in changes,
        owner_id=owner_id,
    )


def approve_draft(
    path: Path,
    report_id: UUID,
    revision: int,
    approved_by: str,
    *,
    approved_by_id: UUID | None = None,
) -> StoredReportDraft | None:
    """Approve the reviewed revision if all three DAP fields contain text."""
    return _update_review(
        path,
        report_id,
        revision,
        "status = 'approved', approved_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), "
        "approved_by = ?, approved_by_id = ?",
        (approved_by, str(approved_by_id) if approved_by_id is not None else None),
        require_complete=True,
    )


def reopen_approved_report(
    path: Path, report_id: UUID, revision: int
) -> StoredReportDraft | None:
    """Reopen the approved report as a new revision and clear approval details."""
    with connect(path) as connection:
        # Check the status and revision in the same statement that reopens the report.
        updated = connection.execute(
            """
            UPDATE report_drafts
            SET status = 'draft', revision = revision + 1,
                approved_at = NULL, approved_by = NULL, approved_by_id = NULL
            WHERE report_id = ? AND revision = ? AND status = 'approved'
            """,
            (str(report_id), revision),
        )
        report = _get_report(connection, report_id)
        if updated.rowcount == 0 and report is not None:
            if report.status != "approved":
                raise ReviewConflict("Only approved reports can be reopened.")
            raise ReviewConflict("Report changed. Reload the current revision.")
        return report


def _update_review(
    path: Path,
    report_id: UUID,
    revision: int,
    assignments: str,
    values: tuple[str | None, ...] = (),
    *,
    require_complete: bool = False,
    check_time_range: bool = False,
    owner_id: UUID | None = None,
) -> StoredReportDraft | None:
    """Update the matching draft revision and read it in the same transaction."""
    complete = (
        "AND data <> '' AND assessment <> '' AND plan <> ''" if require_complete else ""
    )
    owner = str(owner_id) if owner_id is not None else None
    with connect(path) as connection:
        # Check status and revision in the UPDATE so stale requests cannot write.
        # The callers build assignments from schema fields or fixed approval SQL.
        updated = connection.execute(
            f"""
            UPDATE report_drafts SET {assignments}, revision = revision + 1
            WHERE report_id = ? AND revision = ? AND status = 'draft' {complete}
                AND (? IS NULL OR owner_id = ?)
            """,  # nosec B608
            (*values, str(report_id), revision, owner, owner),
        )
        report = _get_report(connection, report_id)
        if report is not None and owner_id is not None and report.owner_id != owner_id:
            return None
        if updated.rowcount == 0 and report is not None:
            if report.status == "approved":
                raise ReviewConflict("Approved reports are read-only.")
            if require_complete and report.revision == revision:
                raise ReviewConflict(
                    "Complete all three DAP sections before approving."
                )
            raise ReviewConflict("Report changed. Reload the current revision.")
        if check_time_range and report is not None and report.metadata is not None:
            # A partial edit can conflict with the other saved time. If the
            # combined range is invalid, the transaction rolls back the edit.
            report.metadata.validate_time_range()
        return report


def _get_report(
    connection: sqlite3.Connection,
    report_id: UUID,
    *,
    viewer: UserAccount | None = None,
) -> StoredReportDraft | None:
    """Read a report using the caller's connection and transaction."""
    # The column list comes from the schema. The report ID is bound separately.
    owner_clause = ""
    parameters = [str(report_id)]
    if viewer is not None and viewer.role != "admin":
        owner_clause = "AND owner_id = ?"
        parameters.append(str(viewer.user_id))
    row = connection.execute(
        f"""
        SELECT owner_id, notes, data, assessment, plan, status, revision, approved_at, approved_by,
               {_METADATA_COLUMNS}
        FROM report_drafts WHERE report_id = ? {owner_clause}
        """,  # nosec B608
        tuple(parameters),
    ).fetchone()
    if row is None:
        return None
    # Rebuild the nested sections from the flat SQLite row.
    (
        owner_id,
        notes,
        data,
        assessment,
        plan,
        status,
        revision,
        approved_at,
        approved_by,
        *details,
    ) = row
    return StoredReportDraft.model_validate(
        {
            "report_id": report_id,
            "owner_id": owner_id,
            "notes": notes,
            "sections": DraftSections(data=data, assessment=assessment, plan=plan),
            "metadata": _read_metadata(details),
            "status": status,
            "revision": revision,
            "approved_at": approved_at,
            "approved_by": approved_by,
        }
    )


def _read_metadata(values: list[str | None]) -> SavedReportMetadata | None:
    """Build metadata from the selected columns, or return None if all are empty."""
    if not any(values):
        return None
    return SavedReportMetadata.model_validate(
        dict(zip(_METADATA_FIELDS, values, strict=True))
    )


def _casefold(value: str | None) -> str | None:
    """Normalize text for case-insensitive matching while preserving SQL NULL."""
    return value.casefold() if value is not None else None
