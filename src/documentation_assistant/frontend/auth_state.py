"""Keep browser-session identity separate from report and widget state."""

from datetime import datetime
from time import time

import streamlit as st


def clear_session(notice: str | None = None) -> None:
    """Remove credentials, reports, notes, filters, and widget state together.

    HTTP clients hold no tokens or report data and may safely keep their pooled
    connections. Do not clear a shared cache or modify client default headers.
    """
    for key in list(st.session_state):
        del st.session_state[key]
    if notice:
        st.session_state["auth_notice"] = notice


def session_expired() -> bool:
    """Treat absent, malformed, or timezone-free expiry values as expired."""
    try:
        expires = datetime.fromisoformat(st.session_state["auth_expires_at"])
        return expires.tzinfo is None or expires.timestamp() <= time()
    except (KeyError, TypeError, ValueError, OverflowError):
        return True


def is_admin() -> bool:
    """Use the account returned by FastAPI to choose visible review controls."""
    return st.session_state.get("auth_user", {}).get("role") == "admin"


def owns_report(report: dict) -> bool:
    """An unassigned report never belongs to an anonymous or signed-in user."""
    user_id = st.session_state.get("auth_user", {}).get("user_id")
    return bool(user_id) and report.get("owner_id") == user_id
