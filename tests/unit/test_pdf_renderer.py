"""Check the DAP template renderer independently of the API."""

import re
from datetime import date, time
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
