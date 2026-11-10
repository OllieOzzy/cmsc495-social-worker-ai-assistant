"""Test SQLite connection setup and cleanup."""

from unittest.mock import ANY, MagicMock

import pytest

from documentation_assistant.backend.db import connection


@pytest.mark.parametrize("fails", [False, True], ids=["success", "error"])
def test_connect_exits_transaction_and_closes_connection(monkeypatch, tmp_path, fails):
    """Verify transaction exit and connection cleanup on success or error."""
    path = tmp_path / "nested" / "test.db"
    sqlite_connect = MagicMock()
    db = sqlite_connect.return_value
    db.execute.return_value.__iter__.return_value = [
        (column,) for column in connection._OPTIONAL_COLUMNS
    ]
    monkeypatch.setattr(connection.sqlite3, "connect", sqlite_connect)

    # Raise inside the context to exercise cleanup after a failed write.
    if fails:
        with pytest.raises(RuntimeError, match="write failed") as error:
            with connection.connect(path):
                raise RuntimeError("write failed")
        db.__exit__.assert_called_once_with(RuntimeError, error.value, ANY)
    else:
        with connection.connect(path) as opened:
            assert opened is db
            db.close.assert_not_called()
        db.__exit__.assert_called_once_with(None, None, None)

    assert path.parent.is_dir()
    sqlite_connect.assert_called_once_with(path)
    create, inspect = db.execute.call_args_list
    assert "CREATE TABLE IF NOT EXISTS report_drafts" in create.args[0]
    assert "pragma_table_info" in inspect.args[0]
    db.close.assert_called_once()
