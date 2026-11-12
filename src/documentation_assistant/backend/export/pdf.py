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
_PAGE_HEIGHT = letter[1]
_DAP_STYLE = ParagraphStyle("DAP text", fontSize=10, leading=13)


def render_report_pdf(report: StoredReportDraft) -> bytes:
    """Return a one-page PDF containing the report's saved DAP text."""
    overlay = BytesIO()
    canvas = Canvas(overlay, pagesize=letter)

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
        _, used_height = paragraph.wrap(514, height)
        if used_height > height:
            raise ValueError(f"{label} exceeds the space on the first PDF page.")
        paragraph.drawOn(canvas, 49, _PAGE_HEIGHT - top - used_height)

    if report.status == "draft":
        canvas.setFillColor(HexColor("#862B24"))
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawRightString(568.8, _PAGE_HEIGHT - 36, "DRAFT")
    canvas.setFillColorRGB(0, 0, 0)
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(568.8, 42, "Page 1")
    canvas.save()

    writer = PdfWriter()
    page = writer.add_page(PdfReader(_TEMPLATE).pages[0])
    page.merge_page(PdfReader(overlay).pages[0])
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
