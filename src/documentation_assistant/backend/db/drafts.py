"""Save and retrieve DAP drafts and their source notes."""

from pathlib import Path
from uuid import UUID, uuid4

from documentation_assistant.backend.db.connection import connect
from documentation_assistant.backend.schemas.reports import (
    DAPSections,
    StoredReportDraft,
)


def save_draft(path: Path, notes: str, sections: DAPSections) -> StoredReportDraft:
    """Insert a draft with a new ID and return it after the write commits."""
    draft = StoredReportDraft(report_id=uuid4(), notes=notes, sections=sections)
    with connect(path) as connection:
        connection.execute(
            """
            INSERT INTO report_drafts (report_id, notes, data, assessment, plan)
            VALUES (?, ?, ?, ?, ?)
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
