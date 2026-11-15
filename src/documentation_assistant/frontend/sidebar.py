"""Display saved reports, search filters, and backend status."""

import streamlit as st

from .api_client import ollama_is_reachable, request_api
from .forms import TEXT_FIELDS, date_input
from .reports import open_report, reset_report_entry

FILTER_FIELDS = {
    field: TEXT_FIELDS[field]
    for field in ("student_name", "student_id", "school", "grade", "social_worker_name")
}
FILTER_FIELDS["approved_by"] = "Approver"
STATUS_LABELS = {"": "All statuses", "draft": "Draft", "approved": "Approved"}


def clear_report_filters():
    """Reset both the applied filters and their input values."""
    for field in (*FILTER_FIELDS, "status", "date_from", "date_to"):
        st.session_state.pop(f"filter_{field}", None)
    st.session_state.pop("active_report_filters", None)


def report_filters():
    """Apply the report search parameters accepted by FastAPI."""
    with st.expander("Filter report"), st.form("report_filters"):
        filters = {
            field: st.text_input(label, key=f"filter_{field}", max_chars=200).strip()
            for field, label in FILTER_FIELDS.items()
        }
        filters["status"] = st.selectbox(
            "Status",
            options=list(STATUS_LABELS),
            format_func=STATUS_LABELS.__getitem__,
            key="filter_status",
        )
        date_from = date_input("Service date from", key="filter_date_from")
        date_to = date_input("Service date to", key="filter_date_to")
        filters.update(date_from=date_from, date_to=date_to)
        with st.container(horizontal=True, gap="small"):
            apply_filters = st.form_submit_button("Apply filters")
            st.form_submit_button("Clear filters", on_click=clear_report_filters)
        if apply_filters:
            if date_from and date_to and date_from > date_to:
                st.error("Choose a start date on or before the end date.")
            else:
                st.session_state["active_report_filters"] = {
                    field: value for field, value in filters.items() if value
                }
    return st.session_state.get("active_report_filters", {})


def report_label(report):
    """Make reports distinguishable in the sidebar."""
    metadata = report.get("metadata") or {}
    name = (
        metadata.get("student_name") or metadata.get("student_id") or "Untitled report"
    )
    report_date = metadata.get("date_of_service")
    parts = [name, report_date, report["report_id"][:8], report["status"].capitalize()]
    return " · ".join(part for part in parts if part)


def tint_status_button(key: str, reachable: bool | None) -> None:
    """Tint the button using the most recent check result."""
    if reachable is None:
        return
    color = "#22a366" if reachable else "#df5353"
    st.html(
        f"<style>.st-key-{key} button {{"
        f"background-color: color-mix(in srgb, {color} 16%, transparent);"
        f"border-color: {color};"
        "}</style>"
    )


def show_sidebar():
    """Render report navigation and search."""
    with st.sidebar:
        with st.container(horizontal=True, gap="small"):
            check_backend = st.button(
                "Backend Status", key="check_backend", icon=":material/dns:"
            )
            check_ollama = st.button(
                "AI Status", key="check_ollama", icon=":material/smart_toy:"
            )

        if check_backend:
            health = request_api("GET", "/health")
            st.session_state["backend_reachable"] = (
                isinstance(health, dict) and health.get("status") == "ok"
            )
            if st.session_state["backend_reachable"]:
                st.success("FastAPI is reachable.")
        if check_ollama:
            st.session_state["ollama_reachable"] = ollama_is_reachable()
            if st.session_state["ollama_reachable"]:
                st.success("Ollama is reachable.")
            else:
                st.error("Could not reach local Ollama. Check that it is running.")

        tint_status_button("check_backend", st.session_state.get("backend_reachable"))
        tint_status_button("check_ollama", st.session_state.get("ollama_reachable"))

        st.subheader("History Reports")
        if st.button("New report", icon=":material/note_add:"):
            reset_report_entry()
            st.rerun()

        filters = report_filters()
        if not backend_reachable:
            return

        reports = request_api("GET", "/reports", params=filters)
        if reports:
            labels = {item["report_id"]: report_label(item) for item in reports}
            with st.form("open_report"):
                selected_id = st.selectbox(
                    "Report", options=list(labels), format_func=labels.__getitem__
                )
                open_selected = st.form_submit_button(
                    "Open report", icon=":material/folder_open:"
                )
            if open_selected:
                open_report(selected_id)
        elif reports == []:
            st.caption("No matching reports." if filters else "No saved reports yet.")
