"""Display read-only account history to administrators in bounded pages."""

import streamlit as st

from .api_client import request_api
from .auth_state import is_admin

_PAGE_SIZE = 25


def show_audit_history() -> None:
    """Fetch history only when opened; pagination never loads the entire table."""
    if not is_admin():
        st.error("Administrator access required.")
        return
    st.subheader("Account audit history")
    st.caption(
        "Newest actions first. Times are UTC. Names reflect the time of the action. Local operations have no signed-in actor. Password values and report content are never recorded."
    )
    if st.button("Refresh history", key="refresh_user_audit"):
        st.session_state["audit_offset"] = 0
        st.rerun()
    offset = st.session_state.get("audit_offset", 0)
    events = request_api(
        "GET", "/users/audit-events", params={"limit": _PAGE_SIZE + 1, "offset": offset}
    )
    if events is None:
        return
    if not events:
        st.info("No account audit events on this page.")
    else:
        st.dataframe(
            [
                {
                    "Event": event["event_id"],
                    "Time (UTC)": event["occurred_at"],
                    "Actor": event["actor_username"] or "Local operation",
                    "Actor ID": event["actor_id"] or "",
                    "Account": event["target_username"],
                    "Account ID": event["target_id"],
                    "Action": event["action"].replace("_", " "),
                    "Changes": "; ".join(
                        f"{field}: {change['before']} → {change['after']}"
                        for field, change in event["changes"].items()
                    ),
                }
                for event in events[:_PAGE_SIZE]
            ],
            hide_index=True,
        )
    with st.container(horizontal=True):
        previous = st.button("Previous events", disabled=offset == 0)
        next_page = st.button("Next events", disabled=len(events) <= _PAGE_SIZE)
    if previous or next_page:
        st.session_state["audit_offset"] = (
            max(0, offset - _PAGE_SIZE) if previous else offset + _PAGE_SIZE
        )
        st.rerun()
