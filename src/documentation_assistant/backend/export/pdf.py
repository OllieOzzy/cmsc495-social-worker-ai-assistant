"""Render saved reports on the school's DAP PDF template."""

from datetime import date
from html import escape
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph

from documentation_assistant.backend.schemas.reports import (
    SavedReportMetadata,
    StoredReportDraft,
)

_TEMPLATE = (
    Path(__file__).resolve().parents[4]
    / "docs/templates/School_Social_Work_DAP_Session_Note.pdf"
)
_PAGE_WIDTH, _PAGE_HEIGHT = letter
_TEXT_LEFT = 49
_TEXT_WIDTH = 514
_CONTINUATION_TOP = 76
_CONTINUATION_BOTTOM = 720
_HEADING_SPACE = 24
_FIELD_STYLE = ParagraphStyle(
    "Form field", fontSize=8.5, leading=10, allowOrphans=1, allowWidows=1
)
_DAP_STYLE = ParagraphStyle("DAP text", parent=_FIELD_STYLE, fontSize=10, leading=13)


def render_report_pdf(report: StoredReportDraft) -> bytes:
    """Return the school form and continuation pages for the saved report."""
    overlay = BytesIO()
    canvas = Canvas(overlay, pagesize=letter)
    is_draft = report.status == "draft"
    overflow = _draw_form(canvas, report)
    _draw_page_labels(canvas, 1, is_draft)
    _draw_continuations(canvas, overflow, is_draft)
    canvas.save()

    writer = PdfWriter()
    page = writer.add_page(PdfReader(_TEMPLATE).pages[0])
    pages = PdfReader(overlay).pages
    page.merge_page(pages[0])
    for continuation in pages[1:]:
        writer.add_page(continuation)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _draw_form(
    canvas: Canvas, report: StoredReportDraft
) -> list[tuple[str, Paragraph]]:
    """Place saved values in the matching form boxes."""
    metadata = report.metadata or SavedReportMetadata()
    overflow: list[tuple[str, Paragraph]] = []

    def field(
        label: str,
        value: str | date | int | None,
        box: tuple[float, float, float, float],
        style: ParagraphStyle = _FIELD_STYLE,
    ) -> None:
        """Draw a value in its box and carry excess text onto a continuation page."""
        if value is None or value == "":
            return
        markup = "<br/>".join(escape(line) for line in str(value).splitlines())
        remaining, _ = _draw_paragraph(canvas, Paragraph(markup, style), *box)
        if remaining is not None:
            overflow.append((label, remaining))

    # Boxes use (left, top, width, height), measured from the template's top left.
    student = " / ".join(filter(None, (metadata.student_name, metadata.student_id)))
    field("Student name / ID", student, (143, 79, 157, 14))
    field("Grade", metadata.grade, (413, 79, 149, 14))
    field("School", metadata.school, (143, 99, 157, 14))
    field("Date of service", metadata.date_of_service, (413, 99, 149, 14))
    if metadata.start_time or metadata.end_time:
        start = metadata.start_time.strftime("%H:%M") if metadata.start_time else ""
        end = metadata.end_time.strftime("%H:%M") if metadata.end_time else ""
        field("Start / end time", f"{start} / {end}", (143, 119, 157, 14))
    field("Total minutes", metadata.total_minutes, (413, 119, 149, 14))
    field(
        "IEP/504 goal addressed", metadata.iep_504_goal_addressed, (413, 157, 149, 26)
    )

    field("Data", report.sections.data, (_TEXT_LEFT, 219, _TEXT_WIDTH, 105), _DAP_STYLE)
    field(
        "Assessment",
        report.sections.assessment,
        (_TEXT_LEFT, 359, _TEXT_WIDTH, 72),
        _DAP_STYLE,
    )
    field("Plan", report.sections.plan, (_TEXT_LEFT, 467, _TEXT_WIDTH, 62), _DAP_STYLE)

    field(
        "Safety concern description",
        metadata.safety_concern_description,
        (379, 567, 175, 13),
    )
    field(
        "Mandated report details", metadata.mandated_report_details, (271, 587, 283, 13)
    )
    field(
        "Supervisor notification", metadata.supervisor_notification, (271, 607, 283, 13)
    )

    # Draw an x within the template's printed brackets for each selected option.
    canvas.setFont("Helvetica", 5.5)
    for selection, positions, baseline in (
        (
            metadata.session_type,
            {"individual": 142.8, "group": 195.25, "family": 235.41},
            147,
        ),
        (metadata.setting, {"in_person": 412.8, "virtual": 464.78}, 147),
        (
            metadata.service_basis,
            {"iep": 142.8, "504": 173.04, "general_referral": 203.76},
            173,
        ),
        (metadata.safety_concern, {"no": 271.2, "yes": 298.6}, 575.5),
    ):
        if selection is not None:
            canvas.drawCentredString(
                positions[selection] + 3.55, _PAGE_HEIGHT - baseline + 1, "x"
            )
    return overflow


def _draw_paragraph(
    canvas: Canvas,
    paragraph: Paragraph,
    left: float,
    top: float,
    width: float,
    height: float,
) -> tuple[Paragraph | None, float]:
    """Draw the lines that fit and return the remainder and height used."""
    _, used_height = paragraph.wrap(width, height)
    remaining = None
    if used_height > height:
        paragraph, remaining = paragraph.split(width, height)
        _, used_height = paragraph.wrap(width, height)
    paragraph.drawOn(canvas, left, _PAGE_HEIGHT - top - used_height)
    return remaining, used_height


def _draw_continuations(
    canvas: Canvas, overflow: list[tuple[str, Paragraph]], is_draft: bool
) -> None:
    """Continue each overflowing section under its own heading."""
    page_number = 1
    top = _CONTINUATION_BOTTOM
    for label, paragraph in overflow:
        remaining: Paragraph | None = paragraph
        while remaining is not None:
            if top + _HEADING_SPACE + _DAP_STYLE.leading > _CONTINUATION_BOTTOM:
                canvas.showPage()
                page_number += 1
                _draw_page_labels(canvas, page_number, is_draft)
                canvas.setFont("Helvetica-Bold", 14)
                canvas.drawCentredString(
                    _PAGE_WIDTH / 2,
                    _PAGE_HEIGHT - 54,
                    "School Social Work Session Note (DAP) - Continuation",
                )
                top = _CONTINUATION_TOP

            canvas.setFillColor(HexColor("#1D375A"))
            canvas.rect(43, _PAGE_HEIGHT - top - 18, 526, 18, fill=1, stroke=0)
            canvas.setFillColorRGB(1, 1, 1)
            canvas.setFont("Helvetica-Bold", 10)
            canvas.drawString(
                _TEXT_LEFT, _PAGE_HEIGHT - top - 12, f"{label} (continued)"
            )
            canvas.setFillColorRGB(0, 0, 0)

            text_top = top + _HEADING_SPACE
            remaining, used_height = _draw_paragraph(
                canvas,
                remaining,
                _TEXT_LEFT,
                text_top,
                _TEXT_WIDTH,
                _CONTINUATION_BOTTOM - text_top,
            )
            # A split section continues on a new page. The next section can share
            # this page if its heading and at least one line fit below.
            top = _CONTINUATION_BOTTOM if remaining else text_top + used_height + 12


def _draw_page_labels(canvas: Canvas, page_number: int, is_draft: bool) -> None:
    """Number every page and mark every page of a draft."""
    if is_draft:
        canvas.setFillColor(HexColor("#862B24"))
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawRightString(568.8, _PAGE_HEIGHT - 36, "DRAFT")
    canvas.setFillColorRGB(0, 0, 0)
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(568.8, 42, f"Page {page_number}")
