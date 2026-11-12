"""Check the DAP template renderer independently of the API."""

from io import BytesIO
from uuid import uuid4

import pytest
from pypdf import PdfReader

from documentation_assistant.backend.export.pdf import render_report_pdf
from documentation_assistant.backend.schemas.reports import (
    DraftSections,
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


def test_render_report_pdf_rejects_text_that_would_overflow():
    """Reject oversized text until continuation pages are supported."""
    report = StoredReportDraft(
        report_id=uuid4(),
        notes="",
        sections=DraftSections(data="", assessment="", plan="Follow up. " * 200),
    )

    with pytest.raises(ValueError, match="Plan exceeds the space"):
        render_report_pdf(report)
