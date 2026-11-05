import pytest

from scripts.ci_demo import build_demo_report


@pytest.mark.parametrize("notes", ["", "   ", "\n\t"])
def test_missing_notes_are_explicit(notes):
    report = build_demo_report(notes)
    assert report == dict.fromkeys(("data", "assessment", "plan"), "Not documented.")


def test_notes_are_preserved_without_inferred_assessment_or_plan():
    notes = "Synthetic student said they might attend next week."
    report = build_demo_report(f"  {notes}\n")
    assert report["data"] == notes
    assert report["assessment"] == "Not documented."
    assert report["plan"] == "Not documented."
