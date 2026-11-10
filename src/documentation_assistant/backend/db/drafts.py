"""Save and retrieve DAP drafts and their source notes."""

from pathlib import Path
from uuid import UUID, uuid4

from documentation_assistant.backend.db.connection import connect
from documentation_assistant.backend.schemas.reports import (
    DAPSections,
    ReportSummary,
    StoredReportDraft,
)


def save_draft(path: Path, notes: str, sections: DAPSections) -> StoredReportDraft:
    """Insert a draft with a new ID and return it after the write commits."""
    draft = StoredReportDraft(report_id=uuid4(), notes=notes, sections=sections)
    with connect(path) as connection:
        connection.execute(
            """
            INSERT INTO report_drafts
                (report_id, notes, data, assessment, plan, created_at)
            VALUES (?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            """,
            (
                str(draft.report_id),
                notes,
                sections.data,
                sections.assessment,
                sections.plan,
            ),
        )
    return draft


def list_drafts(path: Path) -> list[ReportSummary]:
    """List draft IDs and timestamps in reverse insertion order."""
    with connect(path) as connection:
        rows = connection.execute(
            "SELECT report_id, created_at FROM report_drafts ORDER BY rowid DESC"
        ).fetchall()
    return [
        ReportSummary.model_validate({"report_id": report_id, "created_at": created_at})
        for report_id, created_at in rows
    ]


def get_draft(path: Path, report_id: UUID) -> StoredReportDraft | None:
    """Return the source notes and DAP sections for a saved draft ID."""
    with connect(path) as connection:
        row = connection.execute(
            """
            SELECT notes, data, assessment, plan
            FROM report_drafts WHERE report_id = ?
            """,
            (str(report_id),),
        ).fetchone()
    if row is None:
        return None
    # Rebuild the nested sections from the flat SQLite row.
    notes, data, assessment, plan = row
    return StoredReportDraft(
        report_id=report_id,
        notes=notes,
        sections=DAPSections(data=data, assessment=assessment, plan=plan),
    )
