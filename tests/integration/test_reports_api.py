"""Test report endpoints with temporary SQLite storage and mocked Ollama HTTP."""

import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from documentation_assistant.backend.main import create_app

NOTES = "Synthetic student practiced a breathing exercise."


@pytest.fixture
def app(monkeypatch, tmp_path):
    """Create a FastAPI app with a database isolated to the current test."""
    monkeypatch.setenv("DAP_DB_PATH", str(tmp_path / "test.db"))
    return create_app()


@pytest.fixture
def mock_ollama(monkeypatch):
    """Provide a way to replace the Ollama client's HTTP transport."""
    original_client = httpx.AsyncClient

    # Keep the real client so requests and responses follow the usual HTTPX path.
    def configure(handler):
        """Route outgoing Ollama requests to the supplied handler."""

        def make_client(**kwargs):
            """Create an HTTPX client with the test transport."""
            return original_client(transport=httpx.MockTransport(handler), **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", make_client)

    return configure


def test_generation_returns_an_unapproved_draft(app, mock_ollama):
    """Verify generation saves an unapproved draft with its source notes."""
    sections = {
        "data": NOTES,
        "assessment": "Not documented.",
        "plan": "Not documented.",
    }

    def reply(request):
        """Check the Ollama request and return a completed draft."""
        payload = json.loads(request.content)
        assert request.url == "http://127.0.0.1:11434/api/chat"
        assert payload["messages"][1] == {"role": "user", "content": NOTES}
        assert set(payload["format"]["required"]) == {"data", "assessment", "plan"}
        return httpx.Response(
            200, json={"done": True, "message": {"content": json.dumps(sections)}}
        )

    mock_ollama(reply)
    with TestClient(app) as client:
        response = client.post("/reports/generate", json={"notes": NOTES})
    assert response.status_code == 200
    draft = response.json()
    report_id = draft["report_id"]
    assert draft == {"report_id": report_id, "status": "draft", "sections": sections}

    # A fresh app instance must recover the draft from the same database file.
    with TestClient(create_app()) as client:
        retrieved = client.get(f"/reports/{report_id}")
        assert client.get(f"/reports/{uuid4()}").status_code == 404
    assert retrieved.status_code == 200
    assert retrieved.json() == {**draft, "notes": NOTES}


def test_saved_drafts_are_retrieved_by_their_own_ids(app, mock_ollama):
    """Verify each report ID retrieves its own notes and generated sections."""

    def reply(request):
        """Build a distinct draft from the notes in each request."""
        notes = json.loads(request.content)["messages"][1]["content"]
        sections = {
            "data": notes,
            "assessment": "Not documented.",
            "plan": "Not documented.",
        }
        return httpx.Response(
            200, json={"done": True, "message": {"content": json.dumps(sections)}}
        )

    mock_ollama(reply)
    notes_by_report = {}
    with TestClient(app) as client:
        for notes in (NOTES, "Synthetic student practiced asking for a break."):
            response = client.post("/reports/generate", json={"notes": notes})
            assert response.status_code == 200
            notes_by_report[response.json()["report_id"]] = notes

    assert len(notes_by_report) == 2
    with TestClient(create_app()) as client:
        for report_id, notes in notes_by_report.items():
            response = client.get(f"/reports/{report_id}")
            assert response.status_code == 200
            assert response.json() == {
                "report_id": report_id,
                "status": "draft",
                "notes": notes,
                "sections": {
                    "data": notes,
                    "assessment": "Not documented.",
                    "plan": "Not documented.",
                },
            }


def test_get_report_rejects_malformed_id(app):
    """Verify FastAPI identifies a malformed report ID as a path error."""
    with TestClient(app) as client:
        response = client.get("/reports/not-a-uuid")

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["path", "report_id"]


def test_blank_notes_never_reach_ollama(app, mock_ollama):
    """Verify request validation rejects blank notes before generation."""

    def unexpected_call(request):
        """Fail if invalid input reaches the Ollama client."""
        pytest.fail("Blank notes should be rejected before calling Ollama")

    mock_ollama(unexpected_call)
    with TestClient(app) as client:
        assert client.post("/reports/generate", json={"notes": "  "}).status_code == 422


def test_invalid_ollama_reply_is_not_saved(app, mock_ollama):
    """Verify an invalid model reply returns an error without creating a draft."""

    def reply(request):
        """Return a completed reply with the required DAP sections missing."""
        return httpx.Response(200, json={"done": True, "message": {"content": "{}"}})

    mock_ollama(reply)
    with TestClient(app) as client:
        response = client.post("/reports/generate", json={"notes": NOTES})
    assert response.status_code == 502
    assert "Ollama" in response.json()["detail"]
    assert not app.state.database_path.exists()
