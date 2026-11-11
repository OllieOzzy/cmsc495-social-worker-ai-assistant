"""Smoke-test the report workflow against a running Ollama server."""

import os

import pytest
from fastapi.testclient import TestClient

from documentation_assistant.backend.main import create_app

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_OLLAMA") != "1",
    reason="Set RUN_LIVE_OLLAMA=1 to test against a running local Ollama server.",
)


def test_live_ollama_generation_saves_a_draft(monkeypatch, tmp_path):
    """Generate DAP sections and retrieve the saved source notes from SQLite."""
    monkeypatch.setenv("DAP_DB_PATH", str(tmp_path / "smoke.db"))
    notes = "The student said they felt nervous before a math test. We practiced paced breathing together."

    with TestClient(create_app()) as client:
        response = client.post("/reports/generate", json={"notes": notes})
        assert response.status_code == 200, response.text
        draft = response.json()
        assert draft["status"] == "draft"
        sections = draft["sections"]
        assert set(sections) == {"data", "assessment", "plan"}
        assert all(section.strip() for section in sections.values())
        assert sections["plan"] == "Not documented."

    with TestClient(create_app()) as client:
        response = client.get(f"/reports/{draft['report_id']}")
        assert response.status_code == 200, response.text
        stored = response.json()
        assert stored["notes"] == notes
        assert stored["sections"] == sections
        assert stored["status"] == "draft"
        assert stored["approved_at"] is None
