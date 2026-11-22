"""Check audit boundaries without accepting arbitrary credential-bearing changes."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from documentation_assistant.backend.db import audit
from documentation_assistant.backend.schemas.audit import AuditChange
from documentation_assistant.backend.schemas.auth import UserAccount


@pytest.mark.parametrize(
    "field", ["password", "password_hash", "access_token", "notes"]
)
def test_recorder_rejects_nonpublic_change_fields(field):
    """An explicit field allowlist prevents logging credentials or report content."""
    connection = MagicMock()
    account = UserAccount(
        user_id=uuid4(),
        username="target",
        display_name="Target",
        created_at=datetime.now(UTC),
    )
    with pytest.raises(ValidationError):
        audit.record_account_event(
            connection,
            actor_id=None,
            target=account,
            action="account_renamed",
            changes={field: AuditChange(before=None, after="Must not be stored")},
        )
    connection.execute.assert_not_called()


@pytest.mark.parametrize("limit, offset", [(0, 0), (101, 0), (25, -1)])
def test_audit_storage_rejects_unbounded_pages(limit, offset):
    """Validate pagination before opening a database connection."""
    with pytest.raises(ValueError, match="page bounds"):
        audit.list_audit_events(Path("does-not-exist.db"), limit=limit, offset=offset)
