"""Render a synthetic DAP report and open it for a local preview."""

import argparse
import sys
import webbrowser
from pathlib import Path
from tempfile import mkdtemp
from uuid import uuid4

# Allow this script to run directly from PyCharm or the terminal.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from documentation_assistant.backend.export.pdf import render_report_pdf
from documentation_assistant.backend.schemas.reports import (
    DraftSections,
    StoredReportDraft,
)


def main() -> None:
    """Write the sample PDF to a temporary directory and open it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--long", action="store_true", help="Preview overflow in all three DAP sections"
    )
    args = parser.parse_args()
    sections = DraftSections(
        data="The student practiced asking for help.",
        assessment="The student completed the second attempt independently.",
        plan="Check in after science on Friday.",
    )
    if args.long:
        sections = DraftSections(
            **{
                field: "\n".join(f"{number}. {text}" for number in range(1, 49))
                for field, text in sections.model_dump().items()
            }
        )
    report = StoredReportDraft(
        report_id=uuid4(),
        notes="Synthetic notes for testing.",
        sections=sections,
    )
    output = Path(mkdtemp(prefix="dap-preview-")) / "dap-preview.pdf"
    output.write_bytes(render_report_pdf(report))
    print(f"PDF preview: {output}")
    webbrowser.open(output.as_uri())


if __name__ == "__main__":
    main()
