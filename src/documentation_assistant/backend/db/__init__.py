"""Expose SQLite operations for saved DAP reports and user accounts."""

from documentation_assistant.backend.db.drafts import (
    ReviewConflict,
    approve_draft,
    assign_report_owner,
    delete_draft,
    edit_draft,
    get_draft,
    list_drafts,
    reopen_approved_report,
    save_draft,
)
from documentation_assistant.backend.db.users import (
    DuplicateUsername,
    create_user,
    get_user_by_id,
    get_user_by_username,
)

__all__ = [
    "DuplicateUsername",
    "ReviewConflict",
    "approve_draft",
    "assign_report_owner",
    "create_user",
    "delete_draft",
    "edit_draft",
    "get_draft",
    "get_user_by_id",
    "get_user_by_username",
    "list_drafts",
    "reopen_approved_report",
    "save_draft",
]
