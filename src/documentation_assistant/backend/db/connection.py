"""Manage SQLite connections and initialize the database schema."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path


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
                created_at TEXT
            )
        """)
        _ensure_created_at(connection)
        yield connection


def _ensure_created_at(connection: sqlite3.Connection) -> None:
    """Add the timestamp column to databases created before report listing."""
    column_query = """
        SELECT 1 FROM pragma_table_info('report_drafts') WHERE name = 'created_at'
    """
    if connection.execute(column_query).fetchone() is None:
        # Recheck under the write lock in case another request migrated it.
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute(column_query).fetchone() is None:
            # Leave existing drafts at NULL because their save times are unknown.
            connection.execute("ALTER TABLE report_drafts ADD COLUMN created_at TEXT")
