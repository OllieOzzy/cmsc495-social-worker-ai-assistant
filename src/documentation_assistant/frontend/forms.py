"""Render shared Streamlit fields and convert their values for the report API."""

from datetime import date, time

import streamlit as st

TEXT_FIELDS = {
    "student_name": "Student name",
    "student_id": "Student ID",
    "school": "School",
    "grade": "Grade",
    "social_worker_name": "Social worker name",
    "social_worker_credential": "Social worker credential",
    "iep_504_goal_addressed": "IEP/504 goal addressed",
}
SESSION_CHOICES = {
    "session_type": (
        "Session type",
        {"individual": "Individual", "group": "Group", "family": "Family"},
    ),
    "setting": ("Setting", {"in_person": "In person", "virtual": "Virtual"}),
    "service_basis": (
        "Service basis",
        {"iep": "IEP", "504": "504", "general_referral": "General referral"},
    ),
}
YES_NO = {"yes": "Yes", "no": "No"}
REPORTING_CHOICES = {
    "safety_concern": ("Safety concern disclosed or observed?", YES_NO),
}
REPORTING_TEXT_FIELDS = {
    "safety_concern_description": "Safety concern description",
}
REPORTING_BLOCKS = {
    "mandated_report_details": "Mandated report made? (agency, date, report #)",
    "supervisor_notification": "Supervisor / administrator notified",
}
TIME_FORMAT_LABELS = {"12h": "12-hour (AM/PM)", "24h": "24-hour"}


def text_inputs(fields, metadata, disabled):
    """Prefill text fields and return trimmed input or None for blank fields."""
    return {
        field: st.text_input(
            label, value=metadata.get(field) or "", max_chars=200, disabled=disabled
        ).strip()
        or None
        for field, label in fields.items()
    }


def select_inputs(fields, metadata, disabled):
    """Return API choice values, using None for the Not documented option."""
    values = {}
    for field, (label, labels) in fields.items():
        # Show readable labels while keeping the keys expected by the API.
        labels = {
            "": "Not documented",
            **labels,
        }
        options = list(labels)
        values[field] = (
            st.selectbox(
                label,
                options=options,
                index=options.index(metadata.get(field) or ""),
                format_func=labels.__getitem__,
                disabled=disabled,
            )
            or None
        )
    return values


def date_input(label, saved=None, disabled=False, *, key=None):
    """Prefill an optional date and return it as YYYY-MM-DD or None."""
    value = st.date_input(
        label,
        value=date.fromisoformat(saved) if saved else None,
        disabled=disabled,
        key=key,
    )
    return value.isoformat() if value is not None else None


def apply_time_format(key):
    """Remember the display format for the current Streamlit session."""
    st.session_state["time_format"] = st.session_state[key]


def color_expander(key, color, *, body_color=None, header_text_color="white"):
    """Color the expander header and optionally tint its body separately."""
    # Scope the colors to the expander with this widget key.
    scope = f".st-key-{key} [data-testid='stExpander']"
    body_background = color if body_color is None else body_color
    label_color = "white" if body_color is None else "inherit"
    st.html(
        f"<style>{scope} summary {{"
        f"background-color: {color}; color: {header_text_color};}}"
        f"{scope} summary * {{color: {header_text_color};}}"
        f"{scope} [data-testid='stExpanderDetails'] "
        f"{{background-color: {body_background}; color: {label_color};}}"
        f"{scope} [data-testid='stWidgetLabel'] p {{color: {label_color};}}"
        "</style>"
    )


def session_details(metadata, *, form_key, disabled=False):
    """Render session details and return metadata for the report request.

    Prefill the saved values and disable metadata inputs for approved reports.
    The social worker supplies the risk and mandated reporting details.
    """
    with st.expander("Session Details"):
        values = text_inputs(TEXT_FIELDS, metadata, disabled)
        values["date_of_service"] = date_input(
            "Date of service", metadata.get("date_of_service"), disabled
        )
        time_format = st.session_state.get("time_format", "24h")
        format_key = f"{form_key}_time_format"
        with st.container(horizontal=True, gap="small", vertical_alignment="bottom"):
            st.radio(
                "Time format",
                options=list(TIME_FORMAT_LABELS),
                index=list(TIME_FORMAT_LABELS).index(time_format),
                format_func=TIME_FORMAT_LABELS.__getitem__,
                horizontal=True,
                key=format_key,
            )
            # Submitting the form preserves pending edits while changing the display.
            st.form_submit_button(
                "Apply time format", on_click=apply_time_format, args=(format_key,)
            )
        for field, label in (("start_time", "Start time"), ("end_time", "End time")):
            saved_time = metadata.get(field)
            clock_time = st.time_input(
                label,
                value=time.fromisoformat(saved_time) if saved_time else None,
                key=f"{form_key}_{field}",
                step=60,
                format=time_format,
                disabled=disabled,
            )
            # The display can use AM/PM. The API receives a local ISO time.
            values[field] = clock_time.isoformat() if clock_time is not None else None
        if metadata.get("total_minutes") is not None:
            # FastAPI calculates the duration from the saved start and end times.
            st.caption(f"Total minutes: {metadata['total_minutes']}")
        values.update(select_inputs(SESSION_CHOICES, metadata, disabled))

    risk_key = f"{form_key}_risk_reporting"
    color_expander(risk_key, "#862b24", body_color="rgba(223, 83, 83, 0.12)")
    with st.expander(
        "Risk & Mandated Reporting (completed by social worker only)", key=risk_key
    ):
        values.update(select_inputs(REPORTING_CHOICES, metadata, disabled))
        values.update(text_inputs(REPORTING_TEXT_FIELDS, metadata, disabled))
        values.update(
            {
                field: st.text_area(
                    label,
                    value=metadata.get(field) or "",
                    max_chars=1000,
                    disabled=disabled,
                ).strip()
                or None
                for field, label in REPORTING_BLOCKS.items()
            }
        )
    return values
