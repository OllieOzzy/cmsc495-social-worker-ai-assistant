"""Test report endpoints with temporary SQLite storage and mocked Ollama HTTP."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from documentation_assistant.backend.main import create_app
from documentation_assistant.backend.schemas.reports import SavedReportMetadata

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
    assert retrieved.json() == {
        **draft,
        "notes": NOTES,
        "metadata": SavedReportMetadata(draft_source="ai_assisted").model_dump(
            mode="json"
        ),
        "revision": 1,
        "approved_at": None,
        "approved_by": None,
    }


def test_manual_draft_can_be_saved_and_completed_without_ollama(app, mock_ollama):
    """Save a manual draft and approve it after all three sections are filled."""

    def unexpected_ollama_request(_):
        pytest.fail("The manual draft must bypass Ollama")

    mock_ollama(unexpected_ollama_request)
    with TestClient(app) as client:
        created = client.post(
            "/reports/manual",
            json={"notes": NOTES, "metadata": {"student_name": "Example Student"}},
        )
        assert created.status_code == 201
        manual = created.json()
        assert manual["notes"] == NOTES
        assert manual["sections"] == {"data": "", "assessment": "", "plan": ""}
        assert manual["metadata"]["draft_source"] == "handwritten"
        assert manual["metadata"]["student_name"] == "Example Student"
        path = f"/reports/{manual['report_id']}"
        assert client.get(path).json() == manual
        assert (
            client.get("/reports").json()[0]["metadata"]["draft_source"]
            == "handwritten"
        )

        partial = client.patch(
            path,
            json={
                "revision": manual["revision"],
                "sections": {"data": "Handwritten data.", "assessment": "", "plan": ""},
            },
        )
        assert partial.status_code == 200
        approval = {
            "revision": partial.json()["revision"],
            "approved_by": "Taylor Example",
        }
        incomplete = client.post(f"{path}/approve", json=approval)
        assert incomplete.status_code == 409
        assert client.get(path).json() == partial.json()
        source_change = client.patch(
            path,
            json={
                "revision": approval["revision"],
                "metadata": {"draft_source": "ai_assisted"},
            },
        )
        assert source_change.status_code == 422

        completed = client.patch(
            path,
            json={
                "revision": approval["revision"],
                "sections": {
                    "data": "Handwritten data.",
                    "assessment": "Handwritten assessment.",
                    "plan": "Handwritten plan.",
                },
            },
        )
        assert completed.status_code == 200
        approval["revision"] = completed.json()["revision"]
        approved = client.post(f"{path}/approve", json=approval)
        assert approved.status_code == 200
        approved_report = approved.json()
        assert approved_report["status"] == "approved"
        assert approved_report["metadata"]["draft_source"] == "handwritten"


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
        listing = client.get("/reports")
        assert listing.status_code == 200
        summaries = listing.json()
        assert [summary["report_id"] for summary in summaries] == list(
            reversed(notes_by_report)
        )
        for summary in summaries:
            assert set(summary) == {
                "report_id",
                "status",
                "created_at",
                "metadata",
                "approved_by",
            }
            assert summary["approved_by"] is None
            assert summary["status"] == "draft"
            assert datetime.fromisoformat(summary["created_at"]).utcoffset() is not None

        for report_id, notes in notes_by_report.items():
            response = client.get(f"/reports/{report_id}")
            assert response.status_code == 200
            assert response.json() == {
                "report_id": report_id,
                "status": "draft",
                "notes": notes,
                "metadata": SavedReportMetadata(draft_source="ai_assisted").model_dump(
                    mode="json"
                ),
                "revision": 1,
                "approved_at": None,
                "approved_by": None,
                "sections": {
                    "data": notes,
                    "assessment": "Not documented.",
                    "plan": "Not documented.",
                },
            }


def test_list_reports_includes_drafts_saved_before_timestamps(app):
    """Verify the old SQLite schema upgrades without losing saved notes."""
    report_id = str(uuid4())
    with closing(sqlite3.connect(app.state.database_path)) as db, db:
        db.execute("""
            CREATE TABLE report_drafts (
                report_id TEXT PRIMARY KEY NOT NULL,
                notes TEXT NOT NULL,
                data TEXT NOT NULL,
                assessment TEXT NOT NULL,
                plan TEXT NOT NULL
            )
        """)
        db.execute(
            "INSERT INTO report_drafts VALUES (?, ?, ?, ?, ?)",
            (report_id, NOTES, NOTES, "Not documented.", "Not documented."),
        )

    with TestClient(app) as client:
        listing = client.get("/reports")
        assert listing.status_code == 200
        assert listing.json() == [
            {
                "report_id": report_id,
                "status": "draft",
                "created_at": None,
                "metadata": None,
                "approved_by": None,
            }
        ]
        saved = client.get(f"/reports/{report_id}").json()
        assert (saved["notes"], saved["revision"], saved["approved_at"]) == (
            NOTES,
            1,
            None,
        )
        assert client.get("/reports", params={"grade": "8"}).json() == []


def test_review_saves_corrections_and_only_approves_the_current_revision(
    app, mock_ollama
):
    """Verify editing, stale approval, and persisted read-only approval."""
    generated = dict.fromkeys(("data", "assessment", "plan"), "Not documented.")
    approver = {"approved_by": "Taylor Example"}

    def reply(request):
        return httpx.Response(
            200, json={"done": True, "message": {"content": json.dumps(generated)}}
        )

    mock_ollama(reply)
    with TestClient(app) as client:
        created = client.post(
            "/reports/generate",
            json={
                "notes": NOTES,
                "metadata": {"student_id": "SYN-404", "school": "Example Middle"},
            },
        )
        assert created.status_code == 200
        report_url = f"/reports/{created.json()['report_id']}"
        current = client.get(report_url).json()
        edited = {**generated, "data": NOTES}
        edit = client.patch(
            report_url, json={"revision": current["revision"], "sections": edited}
        )
        assert edit.status_code == 200
        assert edit.json() == {**current, "sections": edited, "revision": 2}
        assert (
            client.patch(
                report_url, json={"revision": 1, "sections": generated}
            ).status_code
            == 409
        )
        assert (
            client.post(
                f"{report_url}/approve", json={"revision": 1, **approver}
            ).status_code
            == 409
        )

    with TestClient(create_app()) as client:
        assert client.get(report_url).json() == edit.json()
        assert (
            client.patch(report_url, json={"revision": 2, "metadata": {}}).status_code
            == 422
        )
        corrected = client.patch(
            report_url,
            json={
                "revision": 2,
                "metadata": {
                    "student_id": "SYN-044",
                    "grade": "8",
                    "date_of_service": "2026-11-10",
                    "school": None,
                },
            },
        )
        assert corrected.status_code == 200
        assert corrected.json() == {
            **edit.json(),
            "revision": 3,
            "metadata": {
                **edit.json()["metadata"],
                "student_id": "SYN-044",
                "grade": "8",
                "date_of_service": "2026-11-10",
                "school": None,
            },
        }
        assert client.get("/reports", params={"student_id": "SYN-404"}).json() == []
        assert (
            client.get("/reports", params={"student_id": "SYN-044"}).json()[0][
                "report_id"
            ]
            == created.json()["report_id"]
        )
        assert (
            client.post(
                f"{report_url}/approve", json={"revision": 2, **approver}
            ).status_code
            == 409
        )
        for invalid_approval in ({"revision": 3}, {"revision": 3, "approved_by": " "}):
            assert (
                client.post(f"{report_url}/approve", json=invalid_approval).status_code
                == 422
            )
        approved = client.post(
            f"{report_url}/approve", json={"revision": 3, **approver}
        )
        assert approved.status_code == 200
        approved_at = approved.json()["approved_at"]
        assert datetime.fromisoformat(approved_at).utcoffset() is not None
        assert approved.json() == {
            **corrected.json(),
            "status": "approved",
            "revision": 4,
            "approved_at": approved_at,
            **approver,
        }
        assert (
            client.patch(
                report_url, json={"revision": 4, "metadata": {"student_id": "SYN-404"}}
            ).status_code
            == 409
        )
        assert (
            client.post(
                f"{report_url}/approve", json={"revision": 4, **approver}
            ).status_code
            == 409
        )
        other = client.post("/reports/generate", json={"notes": NOTES})
        assert other.status_code == 200
        assert [item["status"] for item in client.get("/reports").json()] == [
            "draft",
            "approved",
        ]
        drafts = client.get("/reports", params={"status": "draft"}).json()
        assert [item["report_id"] for item in drafts] == [other.json()["report_id"]]
        approved_reports = client.get(
            "/reports", params={"status": "approved", "approved_by": "tAYlOR"}
        ).json()
        assert [item["report_id"] for item in approved_reports] == [
            created.json()["report_id"]
        ]
        assert approved_reports[0]["approved_by"] == approver["approved_by"]
        assert (
            client.get("/reports", params={"approved_by": "Nobody Example"}).json()
            == []
        )
        assert client.get("/reports", params={"status": "all"}).status_code == 422

    with TestClient(create_app()) as client:
        assert client.get(report_url).json() == approved.json()


def test_report_filters_match_saved_metadata(app, mock_ollama):
    """Verify metadata round-trips and filters match singly and together."""
    sections = dict.fromkeys(("data", "assessment", "plan"), "Not documented.")

    def reply(request):
        assert json.loads(request.content)["messages"][1]["content"] == NOTES
        return httpx.Response(
            200, json={"done": True, "message": {"content": json.dumps(sections)}}
        )

    mock_ollama(reply)
    first = {
        "student_name": "Éva Synthetic",
        "student_id": "SYN-001",
        "school": "Example Middle",
        "grade": "8",
        "date_of_service": "2026-10-01",
        "social_worker_name": "Jordan Example",
        "service_basis": "iep",
    }
    second = {
        **first,
        "student_name": "Alex Synthetic",
        "student_id": "SYN-002",
        "date_of_service": "2026-11-01",
        "social_worker_name": "Taylor Example",
    }
    with TestClient(app) as client:
        first_id, second_id = [
            client.post(
                "/reports/generate", json={"notes": NOTES, "metadata": details}
            ).json()["report_id"]
            for details in (first, second)
        ]
        assert client.get(f"/reports/{first_id}").json()[
            "metadata"
        ] == SavedReportMetadata.model_validate(
            {**first, "draft_source": "ai_assisted"}
        ).model_dump(mode="json")
        for params, expected in (
            ({"student_name": "éVA"}, [first_id]),
            ({"social_worker_name": "jORdan", "school": "Example Middle"}, [first_id]),
            ({"student_id": "SYN-002"}, [second_id]),
            ({"school": "example middle", "grade": "8"}, [second_id, first_id]),
            (
                {"grade": "8", "date_from": "2026-10-01", "date_to": "2026-10-01"},
                [first_id],
            ),
            ({"student_name": "%"}, []),
        ):
            response = client.get("/reports", params=params)
            assert response.status_code == 200
            assert [row["report_id"] for row in response.json()] == expected
        invalid = client.get(
            "/reports", params={"date_from": "2026-11-01", "date_to": "2026-10-01"}
        )
        assert invalid.status_code == 422


def test_service_basis_can_be_changed_and_cleared(app, mock_ollama):
    """Save changes to the service basis and reject unknown values."""
    sections = dict.fromkeys(("data", "assessment", "plan"), "Not documented.")
    mock_ollama(
        lambda _: httpx.Response(
            200, json={"done": True, "message": {"content": json.dumps(sections)}}
        )
    )
    with TestClient(app) as client:
        created = client.post(
            "/reports/generate",
            json={"notes": NOTES, "metadata": {"service_basis": "iep"}},
        )
        assert created.status_code == 200
        path = f"/reports/{created.json()['report_id']}"
        report = client.get(path).json()
        assert report["metadata"]["service_basis"] == "iep"

        for value in ("504", "general_referral", None):
            edited = client.patch(
                path,
                json={
                    "revision": report["revision"],
                    "metadata": {"service_basis": value},
                },
            )
            assert edited.status_code == 200
            report = client.get(path).json()
            assert report["metadata"]["service_basis"] == value

        invalid = client.patch(
            path,
            json={
                "revision": report["revision"],
                "metadata": {"service_basis": "other"},
            },
        )
        assert invalid.status_code == 422


def test_session_and_reporting_fields_round_trip(app, mock_ollama):
    """Save the full set of new fields and recalculate duration after editing."""
    sections = dict.fromkeys(("data", "assessment", "plan"), "Not documented.")

    def reply(request):
        assert json.loads(request.content)["messages"][1]["content"] == NOTES
        return httpx.Response(
            200, json={"done": True, "message": {"content": json.dumps(sections)}}
        )

    mock_ollama(reply)
    metadata = {
        "start_time": "09:10:00",
        "end_time": "09:35:00",
        "session_type": "individual",
        "setting": "in_person",
        "iep_504_goal_addressed": "Practice a grounding exercise.",
        "social_worker_credential": "Example credential",
        "safety_concern": "yes",
        "safety_concern_description": "Synthetic example.",
        "mandated_report_details": "Yes. Example agency, 2026-11-10, report EX-001.",
        "supervisor_notification": "No. Synthetic example note.",
        "draft_source": "ai_assisted",
    }
    with TestClient(app) as client:
        created = client.post(
            "/reports/generate", json={"notes": NOTES, "metadata": metadata}
        )
        assert created.status_code == 200
        report_id = created.json()["report_id"]
        path = f"/reports/{report_id}"
        saved = client.get(path).json()
        assert {field: saved["metadata"][field] for field in metadata} == metadata
        assert saved["metadata"]["total_minutes"] == 25

        edited = client.patch(
            path,
            json={
                "revision": saved["revision"],
                "metadata": {"end_time": "09:45", "supervisor_notification": None},
            },
        )
        assert edited.status_code == 200
        reopened = client.get(path).json()["metadata"]
        assert reopened["total_minutes"] == 35
        assert reopened["supervisor_notification"] is None
        assert (
            reopened["mandated_report_details"] == metadata["mandated_report_details"]
        )


def test_separate_reporting_fields_migrate_to_text_blocks(app):
    """Preserve saved entries and allow the merged fields to be cleared."""
    report_id = str(uuid4())
    with closing(sqlite3.connect(app.state.database_path)) as db, db:
        db.execute("""
            CREATE TABLE report_drafts (
                report_id TEXT PRIMARY KEY NOT NULL,
                notes TEXT NOT NULL,
                data TEXT NOT NULL,
                assessment TEXT NOT NULL,
                plan TEXT NOT NULL,
                mandated_report_made TEXT,
                mandated_report_agency TEXT,
                mandated_report_date TEXT,
                mandated_report_number TEXT,
                supervisor_notified TEXT,
                supervisor_notification_details TEXT
            )
        """)
        db.execute(
            "INSERT INTO report_drafts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                report_id,
                NOTES,
                NOTES,
                "Not documented.",
                "Not documented.",
                "yes",
                "Example agency",
                "2026-11-10",
                "EX-001",
                "no",
                "Example note.",
            ),
        )

    with TestClient(app) as client:
        path = f"/reports/{report_id}"
        saved = client.get(path).json()
        assert saved["metadata"]["mandated_report_details"] == (
            "Yes\nAgency: Example agency\nDate: 2026-11-10\nReport #: EX-001"
        )
        assert saved["metadata"]["supervisor_notification"] == "No\nExample note."

        edited = client.patch(
            path,
            json={
                "revision": saved["revision"],
                "metadata": {"mandated_report_details": None},
            },
        )
        assert edited.status_code == 200
        assert client.get(path).json()["metadata"]["mandated_report_details"] is None


def test_list_reports_returns_empty_list_for_new_database(app):
    """Verify the history endpoint returns an empty list before any saves."""
    with TestClient(app) as client:
        response = client.get("/reports")
    assert response.status_code == 200
    assert response.json() == []


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
