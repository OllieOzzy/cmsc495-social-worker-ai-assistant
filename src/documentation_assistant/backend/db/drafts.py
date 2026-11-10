"""Save and retrieve DAP drafts and their source notes."""

from pathlib import Path
from uuid import UUID, uuid4

from documentation_assistant.backend.db.connection import connect
from documentation_assistant.backend.schemas.reports import (
    DAPSections,
    ReportFilters,
    ReportMetadata,
    ReportSummary,
    StoredReportDraft,
)


def save_draft(
    path: Path,
    notes: str,
    sections: DAPSections,
    metadata: ReportMetadata | None = None,
) -> StoredReportDraft:
    """Insert a draft with a new ID and return it after the write commits."""
    draft = StoredReportDraft(
        report_id=uuid4(), notes=notes, sections=sections, metadata=metadata
    )
    details = (metadata or ReportMetadata()).model_dump(mode="json")
    with connect(path) as connection:
        connection.execute(
            """
            INSERT INTO report_drafts
                (report_id, notes, data, assessment, plan, created_at,
                 student_name, student_id, school, grade, date_of_service,
                 social_worker_name)
            VALUES (?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                    ?, ?, ?, ?, ?, ?)
            """,
            (
                str(draft.report_id),
                notes,
                sections.data,
                sections.assessment,
                sections.plan,
                details["student_name"],
                details["student_id"],
                details["school"],
                details["grade"],
                details["date_of_service"],
                details["social_worker_name"],
            ),
        )
    return draft


def list_drafts(
    path: Path, filters: ReportFilters | None = None
) -> list[ReportSummary]:
    """List matching draft summaries in reverse insertion order."""
    values = (filters or ReportFilters()).model_dump(mode="json")
    clauses = []
    parameters = []
    for condition, value in (
        ("instr(casefold(student_name), ?) > 0", _casefold(values["student_name"])),
        ("student_id = ?", values["student_id"]),
        ("casefold(school) = ?", _casefold(values["school"])),
        ("casefold(grade) = ?", _casefold(values["grade"])),
        ("date_of_service >= ?", values["date_from"]),
        ("date_of_service <= ?", values["date_to"]),
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
            SELECT report_id, created_at, student_name, student_id, school, grade,
                   date_of_service, social_worker_name
            FROM report_drafts {where} ORDER BY rowid DESC
            """,
            parameters,
        ).fetchall()
    return [
        ReportSummary.model_validate(
            {
                "report_id": report_id,
                "created_at": created_at,
                "metadata": _read_metadata(details),
            }
        )
        for report_id, created_at, *details in rows
    ]


def get_draft(path: Path, report_id: UUID) -> StoredReportDraft | None:
    """Return the source notes and DAP sections for a saved draft ID."""
    with connect(path) as connection:
        row = connection.execute(
            """
            SELECT notes, data, assessment, plan, student_name, student_id, school,
                   grade, date_of_service, social_worker_name
            FROM report_drafts WHERE report_id = ?
            """,
            (str(report_id),),
        ).fetchone()
    if row is None:
        return None
    # Rebuild the nested sections from the flat SQLite row.
    notes, data, assessment, plan, *details = row
    return StoredReportDraft(
        report_id=report_id,
        notes=notes,
        sections=DAPSections(data=data, assessment=assessment, plan=plan),
        metadata=_read_metadata(details),
    )


def _read_metadata(values: list[str | None]) -> ReportMetadata | None:
    """Restore user-supplied details from the selected SQLite columns."""
    if not any(values):
        return None
    return ReportMetadata.model_validate(
        dict(zip(ReportMetadata.model_fields, values, strict=True))
    )


def _casefold(value: str | None) -> str | None:
    """Normalize text for case-insensitive matching while preserving SQL NULL."""
    return value.casefold() if value is not None else None
