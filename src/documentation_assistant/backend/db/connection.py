"""Manage SQLite connections and initialize the database schema."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

_OPTIONAL_COLUMNS = (
    "created_at",
    "student_name",
    "student_id",
    "school",
    "grade",
    "date_of_service",
    "social_worker_name",
)


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    """Yield a SQLite connection with the drafts table ready to use."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Commit or roll back the transaction before closing the connection.
    with closing(sqlite3.connect(path)) as connection, connection:
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
                social_worker_name TEXT
            )
        """)
        _ensure_optional_columns(connection)
        yield connection


def _ensure_optional_columns(connection: sqlite3.Connection) -> None:
    """Add nullable columns to databases created with an older schema."""
    column_query = "SELECT name FROM pragma_table_info('report_drafts')"
    columns = {name for (name,) in connection.execute(column_query)}
    if all(column in columns for column in _OPTIONAL_COLUMNS):
        return

    # Recheck under the write lock in case another request migrated the database.
    connection.execute("BEGIN IMMEDIATE")
    columns = {name for (name,) in connection.execute(column_query)}
    for column in _OPTIONAL_COLUMNS:
        if column not in columns:
            # Leave old save times and unrecorded report details at NULL.
            connection.execute(f"ALTER TABLE report_drafts ADD COLUMN {column} TEXT")
