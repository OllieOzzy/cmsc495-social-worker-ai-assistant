"""Handle draft creation, review, approval, and PDF download."""

from datetime import datetime
from email.message import Message

import streamlit as st

from .api_client import request_api
from .forms import color_expander, session_details

DAP_FIELDS = {
    "data": "D: Data (what the student reported and what was observed)",
    "assessment": "A: Assessment (progress toward goals, response to intervention)",
    "plan": "P: Plan (next steps, referrals, next session)",
}
DRAFT_SOURCE_LABELS = {"handwritten": "Written by hand", "ai_assisted": "AI-assisted"}


def show_saved_report(report):
    """Switch to the editor using a complete saved report."""
    st.session_state.pop("note_entry", None)
    st.session_state.pop("pending_report_id", None)
    st.session_state["report"] = report
    st.rerun()


def open_report(report_id):
    """Load the saved notes, sections, and revision before editing."""
    report = request_api("GET", f"/reports/{report_id}")
    if report is not None:
        show_saved_report(report)


def reset_report_entry():
    """Close the current report and reset the new report form."""
    st.session_state.pop("report", None)
    st.session_state.pop("note_entry", None)
    st.session_state.pop("pending_report_id", None)
    st.session_state["note_entry_version"] = (
        st.session_state.get("note_entry_version", 0) + 1
    )


def new_report():
    """Start a draft or return to an existing draft with corrected notes."""
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
        payload["revision"] = prefill["revision"]
        if manual:
            payload["sections"] = prefill["sections"]
            updated = request_api("PATCH", path, payload=payload)
        else:
            with st.spinner("Regenerating draft…"):
                updated = request_api(
                    "POST", f"{path}/regenerate", payload=payload, timeout=135
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
        draft = request_api("POST", "/reports/generate", payload=payload, timeout=135)
    if draft is not None:
        # Remember the saved ID before fetching the rest of the report.
        report_id = draft["report_id"]
        st.session_state["pending_report_id"] = report_id
        open_report(report_id)
        st.rerun()


@st.fragment
def report_download(report_id):
    """Fetch the saved PDF on request and let the user save it."""
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
    """Display a report and handle editing, approval, reopening, and deletion."""
    report_id = report["report_id"]
    revision = report["revision"]
    approved = report["status"] == "approved"
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
        metadata = session_details(saved_metadata, form_key=form_key, disabled=approved)
        sections = {
            field: st.text_area(
                label, value=report["sections"][field], disabled=approved
            )
            for field, label in DAP_FIELDS.items()
        }
        discard = False
        with st.container(horizontal=True, gap="small"):
            back = st.form_submit_button(
                "Back to notes", icon=":material/arrow_back:", disabled=approved
            )
            save = st.form_submit_button(
                "Save draft", icon=":material/save:", disabled=approved
            )
            if not approved:
                discard = st.form_submit_button(
                    "Discard changes", icon=":material/undo:"
                )
        approve = delete = reopen = False
        if approved:
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
        else:
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
                approver = st.text_input("Approver name", max_chars=200).strip()
                approve = st.form_submit_button(
                    "Approve saved draft", icon=":material/check_circle:"
                )
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
        report_download(report_id)

    if back:
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
        saved_fields = {field: saved_metadata.get(field) for field in metadata}
        if sections != report["sections"] or metadata != saved_fields:
            st.error("Save your changes before approving this report.")
            return
        if not approver:
            st.error("Enter the approver's name.")
            return
        updated_report = request_api(
            "POST",
            f"/reports/{report_id}/approve",
            payload={"revision": revision, "approved_by": approver},
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
