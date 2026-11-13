"""Render a synthetic DAP report and open it for a local preview."""

import argparse
import os
import sys
import webbrowser
from datetime import UTC, date, datetime, time
from pathlib import Path
from tempfile import mkdtemp
from uuid import uuid4

# Allow this script to run directly from PyCharm or the terminal.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from documentation_assistant.backend.export.pdf import render_report_pdf
from documentation_assistant.backend.schemas.reports import (
    DraftSections,
    SavedReportMetadata,
    StoredReportDraft,
)


def main() -> None:
    """Write the sample PDF to a temporary directory and open it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--long", action="store_true", help="Preview overflow in all three DAP sections"
    )
    parser.add_argument(
        "--approved", action="store_true", help="Preview the reviewer name and date"
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
        status="approved" if args.approved else "draft",
        approved_by="Taylor Example" if args.approved else None,
        approved_at=datetime(2026, 11, 12, 14, 35, tzinfo=UTC)
        if args.approved
        else None,
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
            safety_concern="yes",
            safety_concern_description="Student reported feeling unsafe in the hallway.",
            mandated_report_details="Sample Agency, 2026-11-12, report SYN-001.",
            supervisor_notification="Sample supervisor notified after the session.",
            social_worker_name="Jordan Example",
            social_worker_credential="LCSW-C",
            draft_source="ai_assisted",
        ),
    )
    output = Path(mkdtemp(prefix="dap-preview-")) / "dap-preview.pdf"
    output.write_bytes(render_report_pdf(report))
    print(f"PDF preview: {output}")
    try:
        if sys.platform == "win32":
            # Let Windows open the local path with its default PDF viewer.
            os.startfile(output)
        elif not webbrowser.open(output.as_uri()):
            print("Open the printed path in your PDF viewer.")
    except OSError as error:
        print(f"Could not open the preview automatically: {error}")
        print("Open the printed path in your PDF viewer.")


if __name__ == "__main__":
    main()
