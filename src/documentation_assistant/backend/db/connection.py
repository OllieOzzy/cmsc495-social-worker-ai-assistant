"""Manage SQLite connections and initialize the database schema."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

_ADDED_COLUMNS = {
    "created_at": "TEXT",
    "student_name": "TEXT",
    "student_id": "TEXT",
    "school": "TEXT",
    "grade": "TEXT",
    "date_of_service": "TEXT",
    "social_worker_name": "TEXT",
    "service_basis": "TEXT",
    "start_time": "TEXT",
    "end_time": "TEXT",
    "session_type": "TEXT",
    "setting": "TEXT",
    "iep_504_goal_addressed": "TEXT",
    "social_worker_credential": "TEXT",
    "safety_concern": "TEXT",
    "safety_concern_description": "TEXT",
    "mandated_report_details": "TEXT",
    "supervisor_notification": "TEXT",
    "draft_source": "TEXT",
    "status": "TEXT NOT NULL DEFAULT 'draft'",
    "revision": "INTEGER NOT NULL DEFAULT 1",
    "approved_at": "TEXT",
    "approved_by": "TEXT",
}


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    """Open SQLite and commit or roll back the caller's transaction.

    Call initialize_database before storage operations. Connections do not
    create directories or check the schema; backend startup handles that work.
    """
    # Commit or roll back the transaction before closing the connection.
    with closing(sqlite3.connect(path)) as connection, connection:
        yield connection


def initialize_database(path: Path) -> None:
    """Create report and account tables and upgrade missing report columns."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS report_drafts (
                report_id TEXT PRIMARY KEY NOT NULL,
                notes TEXT NOT NULL,
                data TEXT NOT NULL,
                assessment TEXT NOT NULL,
                plan TEXT NOT NULL,
                created_at TEXT,
                student_name TEXT,
                student_id TEXT,
                school TEXT,
                grade TEXT,
                date_of_service TEXT,
                social_worker_name TEXT,
                service_basis TEXT,
                start_time TEXT,
                end_time TEXT,
                session_type TEXT,
                setting TEXT,
                iep_504_goal_addressed TEXT,
                social_worker_credential TEXT,
                safety_concern TEXT,
                safety_concern_description TEXT,
                mandated_report_details TEXT,
                supervisor_notification TEXT,
                draft_source TEXT,
                status TEXT NOT NULL DEFAULT 'draft',
                revision INTEGER NOT NULL DEFAULT 1,
                approved_at TEXT,
                approved_by TEXT
            )
        """)
        _ensure_added_columns(connection)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY NOT NULL,
                username TEXT NOT NULL COLLATE NOCASE UNIQUE
                    CHECK(length(username) BETWEEN 3 AND 64),
                display_name TEXT NOT NULL
                    CHECK(length(trim(display_name)) BETWEEN 1 AND 200),
                password_hash TEXT NOT NULL CHECK(length(trim(password_hash)) > 0),
                role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user', 'admin')),
                is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
                created_at TEXT NOT NULL
            )
        """)


def _ensure_added_columns(connection: sqlite3.Connection) -> None:
    """Add any missing columns from the report schema."""
    column_query = "SELECT name FROM pragma_table_info('report_drafts')"
    columns = {name for (name,) in connection.execute(column_query)}
    if _ADDED_COLUMNS.keys() <= columns:
        return

    # Acquire the write lock and reread the schema before altering the table.
    connection.execute("BEGIN IMMEDIATE")
    columns = {name for (name,) in connection.execute(column_query)}
    for column, definition in _ADDED_COLUMNS.items():
        if column not in columns:
            connection.execute(
                f"ALTER TABLE report_drafts ADD COLUMN {column} {definition}"
            )
