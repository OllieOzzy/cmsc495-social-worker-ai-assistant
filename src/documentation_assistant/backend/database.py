"""Local SQLite storage for source notes and generated DAP drafts."""

import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from uuid import UUID, uuid4

from documentation_assistant.backend.schemas.reports import (
    DAPSections,
    StoredReportDraft,
)


@contextmanager
def _connect(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS report_drafts (
                report_id TEXT PRIMARY KEY NOT NULL,
                notes TEXT NOT NULL,
                data TEXT NOT NULL,
                assessment TEXT NOT NULL,
                plan TEXT NOT NULL
            )
        """)
        yield connection


def save_draft(path: Path, notes: str, sections: DAPSections) -> StoredReportDraft:
    draft = StoredReportDraft(report_id=uuid4(), notes=notes, sections=sections)
    with _connect(path) as connection:
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
    with _connect(path) as connection:
        row = connection.execute(
            """
            SELECT notes, data, assessment, plan
            FROM report_drafts WHERE report_id = ?
            """,
            (str(report_id),),
        ).fetchone()
    if row is None:
        return None
    notes, data, assessment, plan = row
    return StoredReportDraft(
        report_id=report_id,
        notes=notes,
        sections=DAPSections(data=data, assessment=assessment, plan=plan),
    )
