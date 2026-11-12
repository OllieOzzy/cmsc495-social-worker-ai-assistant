"""Render the saved DAP sections on the school's PDF template."""

from html import escape
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph

from documentation_assistant.backend.schemas.reports import StoredReportDraft

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
_DAP_STYLE = ParagraphStyle(
    "DAP text", fontSize=10, leading=13, allowOrphans=1, allowWidows=1
)


def render_report_pdf(report: StoredReportDraft) -> bytes:
    """Return the school form and any pages needed for its saved DAP text."""
    overlay = BytesIO()
    canvas = Canvas(overlay, pagesize=letter)
    is_draft = report.status == "draft"
    overflow = []

    # The box positions are measured from the top of the letter-size template.
    for label, text, top, height in (
        ("Data", report.sections.data, 219, 105),
        ("Assessment", report.sections.assessment, 359, 72),
        ("Plan", report.sections.plan, 467, 62),
    ):
        if not text:
            continue
        markup = "<br/>".join(escape(line) for line in text.splitlines())
        paragraph = Paragraph(markup, _DAP_STYLE)
        remaining, _ = _draw_paragraph(canvas, paragraph, top, height)
        if remaining is not None:
            overflow.append((label, remaining))

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


def _draw_paragraph(
    canvas: Canvas, paragraph: Paragraph, top: float, height: float
) -> tuple[Paragraph | None, float]:
    """Draw the lines that fit and return the remainder and height used."""
    _, used_height = paragraph.wrap(_TEXT_WIDTH, height)
    remaining = None
    if used_height > height:
        paragraph, remaining = paragraph.split(_TEXT_WIDTH, height)
        _, used_height = paragraph.wrap(_TEXT_WIDTH, height)
    paragraph.drawOn(canvas, _TEXT_LEFT, _PAGE_HEIGHT - top - used_height)
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
                canvas, remaining, text_top, _CONTINUATION_BOTTOM - text_top
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
