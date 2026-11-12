"""Verify PDF downloads from reports saved through the API."""

from io import BytesIO
from uuid import uuid4

from fastapi.testclient import TestClient
from pypdf import PdfReader

from documentation_assistant.backend.main import create_app


def test_download_returns_the_current_saved_report(monkeypatch, tmp_path):
    """Download the same report as a draft and again after approval."""
    monkeypatch.setenv("DAP_DB_PATH", str(tmp_path / "export.db"))
    notes = "Synthetic source notes shown during review."
    sections = {
        "data": "The student practiced asking for help.",
        "assessment": "The student finished the second practice attempt.",
        "plan": "Check in on Friday.",
    }
    with TestClient(create_app()) as client:
        created = client.post(
            "/reports/manual",
            json={"notes": notes, "metadata": {"student_name": "Alex Example"}},
        )
        assert created.status_code == 201
        report_id = created.json()["report_id"]
        path = f"/reports/{report_id}"
        saved = client.patch(
            path, json={"revision": created.json()["revision"], "sections": sections}
        )
        assert saved.status_code == 200
        draft_pdf = client.get(f"{path}/download")

        approved = client.post(
            f"{path}/approve",
            json={
                "revision": saved.json()["revision"],
                "approved_by": "Taylor Example",
            },
        )
        assert approved.status_code == 200
        approved_pdf = client.get(f"{path}/download")

    for response, suffix in ((draft_pdf, "-draft"), (approved_pdf, "")):
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.headers["content-disposition"] == (
            f'attachment; filename="dap-{report_id}{suffix}.pdf"'
        )
        assert response.headers["cache-control"] == "no-store"
        pdf = PdfReader(BytesIO(response.content), strict=True)
        assert len(pdf.pages) == 1
        text = pdf.pages[0].extract_text()
        assert "Alex Example" in text
        assert sections["plan"] in text
        assert notes not in text
        if suffix:
            assert "DRAFT" in text.splitlines()
            assert "Taylor Example" not in text
        else:
            assert "DRAFT" not in text.splitlines()
            assert "Taylor Example" in text
            assert approved.json()["approved_at"][:10] in text


def test_download_returns_404_for_an_unknown_report(monkeypatch, tmp_path):
    """Return the usual API error when there is no saved report to export."""
    monkeypatch.setenv("DAP_DB_PATH", str(tmp_path / "export.db"))
    with TestClient(create_app()) as client:
        response = client.get(f"/reports/{uuid4()}/download")

    assert response.status_code == 404
    assert response.json() == {"detail": "Report draft not found."}
