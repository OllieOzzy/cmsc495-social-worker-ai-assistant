"""Check the DAP template renderer independently of the API."""

import re
from datetime import UTC, date, datetime, time
from io import BytesIO
from uuid import uuid4

import pytest
from pypdf import PdfReader

from documentation_assistant.backend.export.pdf import render_report_pdf
from documentation_assistant.backend.schemas.reports import (
    DraftSections,
    SavedReportMetadata,
    StoredReportDraft,
)


def test_render_report_pdf_places_saved_dap_text_on_the_template():
    """Render a short draft on one page and keep source notes out of the PDF."""
    report = StoredReportDraft(
        report_id=uuid4(),
        notes="Synthetic source notes for review.",
        sections=DraftSections(
            data="Staff & student practiced asking for help.",
            assessment="The student completed the request.",
            plan="Check in on Friday.",
        ),
    )

    pdf = PdfReader(BytesIO(render_report_pdf(report)))
    assert len(pdf.pages) == 1
    text = pdf.pages[0].extract_text()
    assert "School Social Work Session Note (DAP)" in text
    assert report.sections.data in text
    assert report.sections.assessment in text
    assert report.sections.plan in text
    assert "DRAFT" in text.splitlines()
    assert "Page 1" in text.splitlines()
    assert report.notes not in text


def test_render_report_pdf_fills_the_session_details():
    """Render the top block, including the duration and selected options."""
    report = StoredReportDraft(
        report_id=uuid4(),
        notes="",
        sections=DraftSections(data="", assessment="", plan=""),
        metadata=SavedReportMetadata(
            student_name="Alex Example",
            student_id="SYN-001",
            grade="8",
            school="Example Middle School",
            date_of_service=date(2026, 11, 12),
            start_time=time(9, 5),
            end_time=time(9, 30),
            session_type="individual",
            setting="in_person",
            service_basis="iep",
            iep_504_goal_addressed="Practice asking for help during class.",
        ),
    )

    pdf = PdfReader(BytesIO(render_report_pdf(report)))
    assert len(pdf.pages) == 1
    text = pdf.pages[0].extract_text()
    for value in (
        "Alex Example / SYN-001",
        "8",
        "Example Middle School",
        "2026-11-12",
        "09:05 / 09:30",
        "25",
        "Practice asking for help during class.",
    ):
        assert value in text.splitlines()
    assert text.splitlines().count("x") == 3


@pytest.mark.parametrize(
    ("safety_concern", "mark_left"),
    [("no", 273.38), ("yes", 300.78), (None, None)],
)
def test_render_report_pdf_fills_risk_and_reporting(safety_concern, mark_left):
    """Mark the selected safety response and print only saved reporting text."""
    description = "Student reported feeling unsafe in the hallway."
    report = StoredReportDraft(
        report_id=uuid4(),
        notes="Text from the source notes stays out of this form.",
        sections=DraftSections(data="", assessment="", plan=""),
        metadata=SavedReportMetadata(
            safety_concern=safety_concern,
            safety_concern_description=description if safety_concern == "yes" else None,
            mandated_report_details="Sample Agency, 2026-11-12, report SYN-001.",
            supervisor_notification="Sample supervisor notified after the session.",
        ),
    )

    marks = []

    def collect_marks(text, page_matrix, text_matrix, font, font_size):
        if text.strip() == "x":
            marks.append(page_matrix[4] + text_matrix[4])

    pdf = PdfReader(BytesIO(render_report_pdf(report)))
    assert len(pdf.pages) == 1
    text = pdf.pages[0].extract_text(visitor_text=collect_marks)
    assert ("Student reported feeling unsafe in the hallway." in text) == (
        safety_concern == "yes"
    )
    assert "Sample Agency, 2026-11-12, report SYN-001." in text
    assert "Sample supervisor notified after the session." in text
    assert report.notes not in text
    if mark_left is None:
        assert marks == []
    else:
        assert marks == pytest.approx([mark_left], abs=0.01)


def test_render_report_pdf_continues_long_reporting_details():
    """Carry multiline reporting text out of the one-line form box."""
    entries = [f"Sample reporting entry {number:02d}." for number in range(1, 12)]
    report = StoredReportDraft(
        report_id=uuid4(),
        notes="",
        sections=DraftSections(data="", assessment="", plan=""),
        metadata=SavedReportMetadata(mandated_report_details="\n".join(entries)),
    )

    pdf = PdfReader(BytesIO(render_report_pdf(report)))
    first, second = [page.extract_text() for page in pdf.pages]
    assert entries[0] in first
    assert "Mandated report details (continued)" in second
    assert re.findall(r"Sample reporting entry \d{2}\.", first + second) == entries


@pytest.mark.parametrize(
    ("status", "draft_source", "mark_count"),
    [("draft", "handwritten", 1), ("approved", "ai_assisted", 2)],
)
def test_render_report_pdf_fills_worker_and_review_block(
    status, draft_source, mark_count
):
    """Print worker details and show the reviewer and date only when approved."""
    report = StoredReportDraft(
        report_id=uuid4(),
        notes="",
        sections=DraftSections(data="", assessment="", plan=""),
        metadata=SavedReportMetadata(
            social_worker_name="Jordan Example",
            social_worker_credential="LCSW-C",
            draft_source=draft_source,
        ),
        status=status,
        approved_by="Taylor Example",
        approved_at=datetime(2026, 11, 12, 14, 35, tzinfo=UTC),
    )

    pdf = PdfReader(BytesIO(render_report_pdf(report)))
    assert len(pdf.pages) == 1
    text = pdf.pages[0].extract_text()
    assert "Jordan Example" in text
    assert "LCSW-C" in text
    assert sum(line.strip() == "x" for line in text.splitlines()) == mark_count
    assert ("Taylor Example" in text) == (status == "approved")
    assert ("2026-11-12" in text) == (status == "approved")
    assert "Approved by" not in text
    assert "14:35" not in text


@pytest.mark.parametrize("status", ["draft", "approved"])
def test_render_report_pdf_continues_all_three_sections(status):
    """Keep overflow in section order and number every page."""
    sections = {
        field: "\n".join(
            f"{field.upper()}{number:03d} The student practiced asking for help."
            for number in range(1, 81)
        )
        for field in ("data", "assessment", "plan")
    }
    report = StoredReportDraft(
        report_id=uuid4(),
        notes="",
        sections=DraftSections(**sections),
        status=status,
    )

    pdf = PdfReader(BytesIO(render_report_pdf(report)))
    pages = [page.extract_text() for page in pdf.pages]
    assert len(pages) > 2
    for page_number, text in enumerate(pages, start=1):
        assert f"Page {page_number}" in text.splitlines()
        assert ("DRAFT" in text.splitlines()) == (status == "draft")
        if page_number > 1:
            assert "School Social Work Session Note (DAP) - Continuation" in text

    first_page, *continuation_pages = pages
    continuation_text = "\n".join(continuation_pages)
    headings = []
    for field in sections:
        marker = field.upper()
        assert f"{marker}001" in first_page
        heading = f"{field.capitalize()} (continued)"
        headings.append(continuation_text.index(heading))
        # Check every numbered line survived the splits exactly once and in order.
        assert re.findall(rf"\b{marker}\d{{3}}\b", "\n".join(pages)) == [
            f"{marker}{number:03d}" for number in range(1, 81)
        ]
    assert headings == sorted(headings)
