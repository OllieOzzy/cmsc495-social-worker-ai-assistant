"""Verify frontend form values are converted into report API metadata."""

from datetime import date, time
from unittest.mock import MagicMock

import pytest

from documentation_assistant.frontend import forms


@pytest.fixture
def ui(monkeypatch):
    """Return saved widget values with isolated Streamlit session state."""
    streamlit = MagicMock()
    streamlit.session_state = {}
    streamlit.text_input.side_effect = lambda label, **kwargs: kwargs["value"]
    streamlit.text_area.side_effect = lambda label, **kwargs: kwargs["value"]
    streamlit.selectbox.side_effect = lambda label, **kwargs: kwargs["options"][
        kwargs["index"]
    ]
    streamlit.date_input.side_effect = lambda label, **kwargs: kwargs["value"]
    streamlit.time_input.side_effect = lambda label, **kwargs: kwargs["value"]
    monkeypatch.setattr(forms, "st", streamlit)
    return streamlit


@pytest.mark.parametrize(
    ("saved", "expected"), [(None, None), ("", None), ("  ", None), (" Alex ", "Alex")]
)
def test_text_inputs_trim_values_and_convert_blanks_to_none(ui, saved, expected):
    """Normalize optional text before sending it to FastAPI."""
    assert forms.text_inputs(
        {"student_name": "Student name"}, {"student_name": saved}, disabled=False
    ) == {"student_name": expected}


@pytest.mark.parametrize("saved", [None, "", "iep", "504", "general_referral"])
def test_select_inputs_return_api_choice_values(ui, saved):
    """Keep API values while displaying readable service basis labels."""
    field = {"service_basis": forms.SESSION_CHOICES["service_basis"]}

    assert forms.select_inputs(field, {"service_basis": saved}, disabled=True) == {
        "service_basis": saved or None
    }

    options = ui.selectbox.call_args.kwargs
    assert options["format_func"]("") == "Not documented"
    assert options["format_func"]("iep") == "IEP"
    assert options["disabled"] is True


@pytest.mark.parametrize("saved", [None, "2024-02-29", "2026-11-18"])
def test_date_input_prefills_saved_dates_and_returns_iso_text(ui, saved):
    """Preserve optional dates, including a valid leap day."""
    assert forms.date_input("Date", saved, disabled=True, key="service_date") == saved

    ui.date_input.assert_called_once_with(
        "Date",
        value=date.fromisoformat(saved) if saved else None,
        disabled=True,
        key="service_date",
    )


def test_date_input_returns_changed_widget_value(ui):
    """Use the edited date instead of returning the saved prefill."""
    ui.date_input.side_effect = None
    ui.date_input.return_value = date(2026, 11, 19)

    assert forms.date_input("Date", "2026-11-18") == "2026-11-19"


def test_time_format_callback_preserves_other_session_values(ui):
    """Remember the selected display format while retaining pending report edits."""
    ui.session_state.update(edit_time_format="12h", report={"notes": "Synthetic notes"})

    forms.apply_time_format("edit_time_format")

    assert ui.session_state == {
        "edit_time_format": "12h",
        "time_format": "12h",
        "report": {"notes": "Synthetic notes"},
    }


def test_blank_session_details_produce_optional_metadata(ui):
    """Leave undocumented fields empty instead of supplying assumed values."""
    result = forms.session_details({}, form_key="new_report")

    assert result == {
        "student_name": None,
        "student_id": None,
        "school": None,
        "grade": None,
        "social_worker_name": None,
        "social_worker_credential": None,
        "iep_504_goal_addressed": None,
        "date_of_service": None,
        "start_time": None,
        "end_time": None,
        "session_type": None,
        "setting": None,
        "service_basis": None,
        "safety_concern": None,
        "safety_concern_description": None,
        "mandated_report_details": None,
        "supervisor_notification": None,
    }
    assert all(call.kwargs["format"] == "24h" for call in ui.time_input.call_args_list)
    ui.caption.assert_not_called()


@pytest.mark.parametrize("display_format", ["12h", "24h"])
@pytest.mark.parametrize(
    ("start", "end"),
    [("00:00:00", "00:25:00"), ("12:00:00", "12:25:00"), ("15:00:00", "15:25:00")],
)
def test_time_display_formats_preserve_api_times(ui, display_format, start, end):
    """Midnight, noon, and afternoon retain their ISO values in either display."""
    ui.session_state["time_format"] = display_format

    result = forms.session_details(
        {"start_time": start, "end_time": end}, form_key="edit"
    )

    assert result["start_time"] == start
    assert result["end_time"] == end
    assert [call.kwargs["value"] for call in ui.time_input.call_args_list] == [
        time.fromisoformat(start),
        time.fromisoformat(end),
    ]
    assert all(
        call.kwargs["format"] == display_format for call in ui.time_input.call_args_list
    )
    assert [call.kwargs["key"] for call in ui.time_input.call_args_list] == [
        "edit_start_time",
        "edit_end_time",
    ]


def test_approved_report_metadata_is_prefilled_and_disabled(ui):
    """Approved reports display saved metadata with disabled editing controls."""
    metadata = {
        "student_name": "Alex Example",
        "student_id": "SYN-001",
        "school": "Example School",
        "grade": "8",
        "social_worker_name": "Taylor Example",
        "social_worker_credential": "LCSW",
        "iep_504_goal_addressed": "Practice asking for help.",
        "date_of_service": "2026-11-18",
        "start_time": "09:00:00",
        "end_time": "09:25:00",
        "session_type": "individual",
        "setting": "in_person",
        "service_basis": "iep",
        "safety_concern": "no",
        "safety_concern_description": None,
        "mandated_report_details": " Not documented. ",
        "supervisor_notification": " Supervisor notified. ",
        "total_minutes": 25,
    }

    result = forms.session_details(metadata, form_key="approved", disabled=True)

    expected = {key: value for key, value in metadata.items() if key != "total_minutes"}
    expected["mandated_report_details"] = "Not documented."
    expected["supervisor_notification"] = "Supervisor notified."
    assert result == expected
    ui.caption.assert_called_once_with("Total minutes: 25")
    for widget in (
        ui.text_input,
        ui.text_area,
        ui.selectbox,
        ui.date_input,
        ui.time_input,
    ):
        assert all(call.kwargs["disabled"] is True for call in widget.call_args_list)
    assert metadata["mandated_report_details"] == " Not documented. "
