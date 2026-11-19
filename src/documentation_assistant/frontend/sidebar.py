"""Render service status, report filters, and saved-report navigation."""

from time import monotonic

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
_HISTORY_PAGE_SIZE = 25


def clear_report_filters():
    """Clear the search inputs and the filters used for API requests."""
    for field in (*FILTER_FIELDS, "status", "date_from", "date_to"):
        st.session_state.pop(f"filter_{field}", None)
    st.session_state.pop("active_report_filters", None)
    st.session_state.pop("history_offset", None)


def report_filters():
    """Render the filter form and return the last applied query parameters."""
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
                # Omit blank filters from the FastAPI query string.
                st.session_state["active_report_filters"] = {
                    field: value for field, value in filters.items() if value
                }
                st.session_state.pop("history_offset", None)
    return st.session_state.get("active_report_filters", {})


def report_label(report):
    """Build a report label from its name, date, short ID, and status."""
    metadata = report.get("metadata") or {}
    name = (
        metadata.get("student_name") or metadata.get("student_id") or "Untitled report"
    )
    report_date = metadata.get("date_of_service")
    parts = [name, report_date, report["report_id"][:8], report["status"].capitalize()]
    return " · ".join(part for part in parts if part)


def tint_status_button(key: str, reachable: bool) -> None:
    """Color the keyed status button based on service reachability."""
    color = "#22a366" if reachable else "#df5353"
    st.html(
        f"<style>.st-key-{key} button {{"
        f"background-color: color-mix(in srgb, {color} 16%, transparent);"
        f"border-color: {color};"
        "}</style>"
    )


@st.fragment(run_every=60)
def show_service_status() -> bool:
    """Check FastAPI and Ollama and return whether FastAPI is reachable.

    Reuse each session's results for 60 seconds across page reruns. The
    fragment refreshes automatically; buttons immediately recheck their service.
    """
    with st.container(horizontal=True, gap="small"):
        check_backend = st.button(
            "Backend Status", key="check_backend", icon=":material/dns:"
        )
        check_ollama = st.button(
            "AI Status", key="check_ollama", icon=":material/smart_toy:"
        )

    backend_status = st.session_state.get("backend_status_cache")
    if check_backend or backend_status is None or monotonic() - backend_status[1] >= 60:
        # request_api displays connection errors below the status buttons.
        health = request_api("GET", "/health", timeout=3)
        backend_reachable = isinstance(health, dict) and health.get("status") == "ok"
        st.session_state["backend_status_cache"] = (backend_reachable, monotonic())
        if health is not None and not backend_reachable:
            st.error("The report server did not return a healthy status.")
    else:
        backend_reachable = backend_status[0]
        if not backend_reachable:
            st.error(
                "Could not reach the report server. Check that FastAPI is running."
            )

    ollama_status = st.session_state.get("ollama_status_cache")
    if check_ollama or ollama_status is None or monotonic() - ollama_status[1] >= 60:
        ollama_reachable = ollama_is_reachable()
        st.session_state["ollama_status_cache"] = (ollama_reachable, monotonic())
    else:
        ollama_reachable = ollama_status[0]
    tint_status_button("check_backend", backend_reachable)
    tint_status_button("check_ollama", ollama_reachable)

    if check_backend and backend_reachable:
        # A full rerun loads history if an earlier run skipped it.
        if st.session_state.get("history_waiting_for_backend"):
            st.rerun()
        st.success("FastAPI is reachable.")
    if check_ollama:
        if ollama_reachable:
            st.success("Ollama is reachable.")
        else:
            st.error("Could not reach local Ollama. Check that it is running.")
    return backend_reachable


def show_sidebar():
    """Render service status, report filters, and saved-report controls."""
    with st.sidebar:
        backend_reachable = show_service_status()
        st.session_state["history_waiting_for_backend"] = not backend_reachable
        st.subheader("History Reports")
        if st.button("New report", icon=":material/note_add:"):
            reset_report_entry()
            st.rerun()

        filters = report_filters()
        if not backend_reachable:
            # The status panel already reports the connection problem.
            return

        offset = st.session_state.get("history_offset", 0)
        # Fetch one extra summary to detect a next page without a COUNT query.
        reports = request_api(
            "GET",
            "/reports",
            params={**filters, "limit": _HISTORY_PAGE_SIZE + 1, "offset": offset},
        )
        if reports == [] and offset:
            # A deletion can empty the last page; return to the preceding page.
            st.session_state["history_offset"] = max(0, offset - _HISTORY_PAGE_SIZE)
            st.rerun()
        if reports:
            labels = {
                item["report_id"]: report_label(item)
                for item in reports[:_HISTORY_PAGE_SIZE]
            }
            with st.form("open_report"):
                selected_id = st.selectbox(
                    "Report", options=list(labels), format_func=labels.__getitem__
                )
                open_selected = st.form_submit_button(
                    "Open report", icon=":material/folder_open:"
                )
            if open_selected:
                open_report(selected_id)
            st.caption(f"Page {offset // _HISTORY_PAGE_SIZE + 1}")
            with st.container(horizontal=True, gap="small"):
                previous = st.button("Previous", disabled=offset == 0)
                next_page = st.button(
                    "Next", disabled=len(reports) <= _HISTORY_PAGE_SIZE
                )
            if previous or next_page:
                st.session_state["history_offset"] = (
                    max(0, offset - _HISTORY_PAGE_SIZE)
                    if previous
                    else offset + _HISTORY_PAGE_SIZE
                )
                st.rerun()
        elif reports == []:
            st.caption("No matching reports." if filters else "No saved reports yet.")
