"""Render report entry and review screens and handle their API requests."""

from datetime import datetime
from email.message import Message

import streamlit as st

from documentation_assistant import OLLAMA_REQUEST_TIMEOUT_SECONDS

from .api_client import request_api
from .auth_state import is_admin, owns_report
from .forms import color_expander, session_details

DAP_FIELDS = {
    "data": "D: Data (what the student reported and what was observed)",
    "assessment": "A: Assessment (progress toward goals, response to intervention)",
    "plan": "P: Plan (next steps, referrals, next session)",
}
DRAFT_SOURCE_LABELS = {"handwritten": "Written by hand", "ai_assisted": "AI-assisted"}
# Give FastAPI time to return the result after Ollama finishes or times out.
_GENERATION_API_TIMEOUT = OLLAMA_REQUEST_TIMEOUT_SECONDS + 15


def show_saved_report(report):
    """Clear pending entry state and open the saved report for review."""
    st.session_state.pop("note_entry", None)
    st.session_state.pop("pending_report_id", None)
    st.session_state["report"] = report
    st.rerun()


def open_report(report_id):
    """Fetch the full report by ID and open it if the request succeeds."""
    report = request_api("GET", f"/reports/{report_id}")
    if report is not None:
        show_saved_report(report)


def reset_report_entry():
    """Clear the current selection and reset the note entry widgets."""
    st.session_state.pop("report", None)
    st.session_state.pop("note_entry", None)
    st.session_state.pop("pending_report_id", None)
    st.session_state["note_entry_version"] = (
        st.session_state.get("note_entry_version", 0) + 1
    )


def new_report():
    """Create a draft or edit the notes of an existing draft.

    For an existing draft, Save notes keeps the displayed DAP text.
    AI-assisted draft replaces all three DAP sections using the edited notes.
    """
    prefill = st.session_state.get("note_entry", {})
    report_id = prefill.get("report_id")
    form_version = st.session_state.get("note_entry_version", 0)
    form_key = f"new_report_{form_version}"
    with st.form(form_key, enter_to_submit=False):
        notes = st.text_area(
            ":material/description: Session Notes",
            value=prefill.get("notes", ""),
            height=480,
            max_chars=4000,
        )
        metadata = session_details(prefill.get("metadata") or {}, form_key=form_key)
        if report_id:
            st.caption(
                "Creating an AI-assisted draft replaces the current Data, Assessment, and Plan."
            )
        with st.container(horizontal=True, gap="small"):
            manual = st.form_submit_button(
                "Save notes" if report_id else "Written by hand",
                icon=":material/save:" if report_id else ":material/edit_note:",
            )
            generate = st.form_submit_button(
                "AI-assisted draft", icon=":material/smart_toy:"
            )
            discard = st.form_submit_button("Discard changes", icon=":material/undo:")

    if discard:
        # A new form key restores the notes and details from the form's prefill.
        st.session_state["note_entry_version"] = form_version + 1
        st.session_state["report_notice"] = "Unsaved changes discarded."
        st.rerun()

    if not (manual or generate):
        return
    if generate and not notes.strip():
        st.error("Enter session notes to create an AI-assisted draft.")
        return

    payload = {"notes": notes, "metadata": metadata}
    if report_id:
        path = f"/reports/{report_id}"
        # Use the revision from the review screen so stale edits are rejected.
        payload["revision"] = prefill["revision"]
        if manual:
            payload["sections"] = prefill["sections"]
            updated = request_api("PATCH", path, payload=payload)
        else:
            with st.spinner("Regenerating draft…"):
                updated = request_api(
                    "POST",
                    f"{path}/regenerate",
                    payload=payload,
                    timeout=_GENERATION_API_TIMEOUT,
                )
        if updated is not None:
            st.session_state.pop("note_entry")
            st.session_state["report"] = updated
            st.session_state["report_notice"] = "Draft updated."
            st.rerun()
        return

    if manual:
        draft = request_api("POST", "/reports/manual", payload=payload)
        if draft is not None:
            show_saved_report(draft)
        return

    with st.spinner("Generating draft…"):
        draft = request_api(
            "POST",
            "/reports/generate",
            payload=payload,
            timeout=_GENERATION_API_TIMEOUT,
        )
    if draft is not None:
        # Keep the saved ID so a failed fetch can be retried without saving again.
        report_id = draft["report_id"]
        st.session_state["pending_report_id"] = report_id
        open_report(report_id)
        st.rerun()


@st.fragment
def report_download(report_id):
    """Fetch the PDF for the saved report without submitting the review form."""
    st.caption(
        "The PDF uses the latest saved report. Save any edits before downloading."
    )
    with st.container(horizontal=True, gap="small"):
        if not st.button("Prepare PDF", icon=":material/picture_as_pdf:"):
            return
        response = request_api("GET", f"/reports/{report_id}/download", raw=True)
        if response is None:
            return
        if response.headers.get("content-type") != "application/pdf":
            st.error("The report server did not return a PDF.")
            return

        # Use the filename supplied by the API when available.
        headers = Message()
        headers["Content-Disposition"] = response.headers.get("content-disposition", "")
        st.download_button(
            "Download PDF",
            icon=":material/download:",
            data=response.content,
            file_name=headers.get_filename() or f"dap-{report_id}.pdf",
            mime="application/pdf",
            on_click="ignore",
        )


def review_report(report):
    """Show source notes beside the DAP sections and handle report actions.

    Drafts are editable. Approved reports must be reopened before editing.
    """
    report_id = report["report_id"]
    revision = report["revision"]
    approved = report["status"] == "approved"
    admin = is_admin()
    owned = owns_report(report)
    if not (owned or admin):
        reset_report_entry()
        st.session_state["report_notice"] = (
            "That report is no longer available to this account."
        )
        st.rerun()
    editable = owned and not approved
    st.caption(f"{report['status'].capitalize()} · Revision {revision}")
    if approved and report["approved_by"] and report["approved_at"]:
        approval_time = datetime.fromisoformat(report["approved_at"])
        st.text(
            f"Approved by {report['approved_by']} on {approval_time:%Y-%m-%d %H:%M %Z}."
        )

    saved_metadata = report.get("metadata") or {}
    draft_source = DRAFT_SOURCE_LABELS.get(saved_metadata.get("draft_source"))
    if draft_source:
        st.caption(f"Draft source: {draft_source}")
    source, draft = st.columns(2)
    with source:
        st.text_area(
            "Source notes",
            value=report["notes"],
            height=600,
            disabled=True,
            key=f"source_{report_id}_{revision}",
        )
    form_version = st.session_state.get("edit_form_version", 0)
    form_key = f"edit_{report_id}_{revision}_{form_version}"
    with draft, st.form(form_key, enter_to_submit=False):
        metadata = session_details(
            saved_metadata, form_key=form_key, disabled=not editable
        )
        sections = {
            field: st.text_area(
                label, value=report["sections"][field], disabled=not editable
            )
            for field, label in DAP_FIELDS.items()
        }
        discard = False
        with st.container(horizontal=True, gap="small"):
            back = st.form_submit_button(
                "Back to notes", icon=":material/arrow_back:", disabled=not editable
            )
            save = st.form_submit_button(
                "Save draft", icon=":material/save:", disabled=not editable
            )
            if editable:
                discard = st.form_submit_button(
                    "Discard changes", icon=":material/undo:"
                )
        approve = delete = reopen = False
        if approved and admin:
            reopen_key = f"{form_key}_reopen"
            color_expander(
                reopen_key,
                "#f2c94c",
                body_color="rgba(242, 201, 76, 0.18)",
                header_text_color="#2c2100",
            )
            st.html(
                f"<style>.st-key-{reopen_key} button {{"
                "background-color: #f7dc82; border-color: #b08a19; color: #2c2100;"
                "}"
                f".st-key-{reopen_key} button:hover {{"
                "background-color: #f2ce62; border-color: #8a6911; color: #2c2100;"
                "}</style>"
            )
            with st.expander(
                "Reopen for correction", key=reopen_key, icon=":material/history:"
            ):
                confirm_reopen = st.checkbox(
                    "I understand this clears the current approval"
                )
                reopen = st.form_submit_button(
                    "Reopen as draft", icon=":material/history:"
                )
        if not approved and admin:
            approval_key = f"{form_key}_approval"
            color_expander(
                approval_key, "#17603c", body_color="rgba(34, 163, 102, 0.12)"
            )
            st.html(
                f"<style>.st-key-{approval_key} button:hover {{"
                "background-color: rgba(34, 163, 102, 0.16);"
                "border-color: #22a366;"
                "color: inherit;"
                "}</style>"
            )
            with st.expander("Approval", key=approval_key, icon=":material/verified:"):
                st.caption("Approval records your signed-in administrator account.")
                approve = st.form_submit_button(
                    "Approve saved draft", icon=":material/check_circle:"
                )
        if editable:
            delete_key = f"{form_key}_delete"
            color_expander(delete_key, "#862b24", body_color="rgba(223, 83, 83, 0.12)")
            st.html(
                f"<style>.st-key-{delete_key} button:hover {{"
                "background-color: rgba(223, 83, 83, 0.16);"
                "border-color: #df5353;"
                "color: inherit;"
                "}</style>"
            )
            with st.expander("Delete draft", key=delete_key, icon=":material/delete:"):
                confirm_delete = st.checkbox(
                    "I understand this permanently deletes the draft"
                )
                delete = st.form_submit_button("Delete draft", icon=":material/delete:")

    with draft:
        # Keep PDF preparation outside the form so it can run independently.
        report_download(report_id)

    if back:
        # Carry the edits into the notes screen until the user saves or regenerates.
        st.session_state["note_entry"] = {
            "report_id": report_id,
            "revision": revision,
            "notes": report["notes"],
            "metadata": metadata,
            "sections": sections,
        }
        st.session_state["note_entry_version"] = (
            st.session_state.get("note_entry_version", 0) + 1
        )
        st.session_state.pop("report")
        st.rerun()

    if discard:
        # A new form key resets the widgets to the values in the saved report.
        st.session_state["edit_form_version"] = form_version + 1
        st.session_state["report_notice"] = "Unsaved changes discarded."
        st.rerun()

    if delete:
        if not confirm_delete:
            st.error("Confirm that you want to delete this draft.")
            return
        deleted = request_api(
            "DELETE", f"/reports/{report_id}", params={"revision": revision}
        )
        if deleted is True:
            reset_report_entry()
            st.session_state["report_notice"] = "Draft deleted."
            st.rerun()
        return

    if save:
        updated_report = request_api(
            "PATCH",
            f"/reports/{report_id}",
            payload={"revision": revision, "sections": sections, "metadata": metadata},
        )
        message = "Draft saved."
    elif approve:
        # Approval applies to the saved revision, so require pending edits to be saved.
        saved_fields = {field: saved_metadata.get(field) for field in metadata}
        if sections != report["sections"] or metadata != saved_fields:
            st.error("Save your changes before approving this report.")
            return
        updated_report = request_api(
            "POST",
            f"/reports/{report_id}/approve",
            payload={"revision": revision},
        )
        message = "Report approved."
    elif reopen:
        if not confirm_reopen:
            st.error("Confirm that you want to reopen this report.")
            return
        updated_report = request_api(
            "POST", f"/reports/{report_id}/reopen", payload={"revision": revision}
        )
        message = "Report reopened as a draft."
    else:
        return

    if updated_report is not None:
        st.session_state["report"] = updated_report
        st.session_state["report_notice"] = message
        st.rerun()
