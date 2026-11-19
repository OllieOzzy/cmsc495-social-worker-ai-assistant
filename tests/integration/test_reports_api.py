"""Test report endpoints with temporary SQLite storage and mocked Ollama HTTP."""

import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime
from threading import Event
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


def test_openapi_manual_draft_examples_match_the_api(app):
    """Submit the Swagger request example and compare it with the response example."""
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()
        operation = schema["paths"]["/reports/manual"]["post"]
        request_body = operation["requestBody"]["content"]["application/json"]
        response = client.post(
            "/reports/manual", json=request_body["examples"]["session"]["value"]
        )
        assert response.status_code == 201
        path = "/reports/{report_id}"
        edit_body = schema["paths"][path]["patch"]["requestBody"]["content"][
            "application/json"
        ]
        report_id = response.json()["report_id"]
        edited = client.patch(
            f"/reports/{report_id}", json=edit_body["examples"]["session"]["value"]
        )
        assert edited.status_code == 200
        download = schema["paths"][f"{path}/download"]["get"]
        parameter = next(p for p in download["parameters"] if p["name"] == "report_id")
        assert parameter["required"]
        assert "saved reports" in parameter["description"]

    documented = operation["responses"]["201"]["content"]["application/json"]["example"]
    actual = response.json()
    for field in (
        "sections",
        "notes",
        "status",
        "revision",
    ):
        assert actual[field] == documented[field]
    assert {
        field: actual["metadata"][field] for field in documented["metadata"]
    } == documented["metadata"]
    assert actual["approved_at"] is None
    assert actual["approved_by"] is None


@pytest.mark.parametrize("operation", ["generate", "regenerate"])
def test_openapi_ai_draft_examples_accept_session_times(app, mock_ollama, operation):
    """Submit the documented AI request and check the saved session duration."""
    sections = {
        "data": "The student practiced asking for help.",
        "assessment": "Not documented.",
        "plan": "Not documented.",
    }
    mock_ollama(
        lambda request: httpx.Response(
            200, json={"done": True, "message": {"content": json.dumps(sections)}}
        )
    )

    with TestClient(app) as client:
        paths = client.get("/openapi.json").json()["paths"]
        route = "/reports/generate"
        if operation == "regenerate":
            created = client.post("/reports/manual", json={})
            assert created.status_code == 201
            route = "/reports/{report_id}/regenerate"
            url = route.format(report_id=created.json()["report_id"])
        else:
            url = route

        body = paths[route]["post"]["requestBody"]["content"]["application/json"]
        response = client.post(url, json=body["examples"]["session"]["value"])
        assert response.status_code == 200
        report_id = response.json()["report_id"]
        saved = client.get(f"/reports/{report_id}")
        assert saved.status_code == 200

    metadata = saved.json()["metadata"]
    assert metadata["start_time"] == "09:00:00"
    assert metadata["end_time"] == "09:25:00"
    assert metadata["total_minutes"] == 25


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


@pytest.mark.parametrize("payload", [{}, {"notes": "  "}], ids=["omitted", "blank"])
def test_manual_draft_can_start_without_notes(app, payload):
    """Open and retrieve a blank manual draft for the user to fill in."""
    with TestClient(app) as client:
        created = client.post("/reports/manual", json=payload)
        assert created.status_code == 201
        draft = created.json()
        assert draft["notes"] == ""
        assert draft["sections"] == {"data": "", "assessment": "", "plan": ""}
        assert draft["metadata"]["draft_source"] == "handwritten"
        assert client.get(f"/reports/{draft['report_id']}").json() == draft


def test_delete_draft_requires_the_current_revision(app):
    """Delete a saved draft only after the caller confirms its current revision."""
    with TestClient(app) as client:
        created = client.post("/reports/manual", json={})
        assert created.status_code == 201
        draft = created.json()
        path = f"/reports/{draft['report_id']}"
        assert client.delete(path).status_code == 422

        edited = client.patch(
            path, json={"revision": draft["revision"], "metadata": {"grade": "8"}}
        )
        assert edited.status_code == 200
        stale = client.delete(path, params={"revision": draft["revision"]})
        assert stale.status_code == 409
        assert client.get(path).json() == edited.json()

        params = {"revision": edited.json()["revision"]}
        deleted = client.delete(path, params=params)
        assert deleted.status_code == 204
        assert deleted.content == b""
        assert client.get(path).status_code == 404
        assert client.get("/reports").json() == []
        assert client.delete(path, params=params).status_code == 404


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
        delete_approved = client.delete(report_url, params={"revision": 4})
        assert delete_approved.status_code == 409
        assert delete_approved.json()["detail"] == "Approved reports cannot be deleted."
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


def test_reopen_clears_approval_and_allows_corrections(app):
    """Reopen the current revision in place and approve it again after editing."""
    with TestClient(app) as client:
        paths = client.get("/openapi.json").json()["paths"]
        create = paths["/reports/manual"]["post"]["requestBody"]["content"][
            "application/json"
        ]
        reopen = paths["/reports/{report_id}/reopen"]["post"]
        example = reopen["responses"]["200"]["content"]["application/json"]["example"]
        reopen_payload = reopen["requestBody"]["content"]["application/json"][
            "examples"
        ]["approved"]["value"]
        sections = {
            "data": create["examples"]["session"]["value"]["notes"],
            "assessment": "Not documented.",
            "plan": "Not documented.",
        }
        created = client.post(
            "/reports/manual",
            json=create["examples"]["session"]["value"],
        )
        assert created.status_code == 201
        path = f"/reports/{created.json()['report_id']}"
        saved = client.patch(path, json={"revision": 1, "sections": sections})
        assert saved.status_code == 200
        approval = client.post(
            f"{path}/approve", json={"revision": 2, "approved_by": "Taylor Example"}
        )
        assert approval.status_code == 200
        approved = approval.json()

        stale = client.post(f"{path}/reopen", json={"revision": 2})
        assert stale.status_code == 409
        assert client.get(path).json() == approved

        response = client.post(f"{path}/reopen", json=reopen_payload)
        assert response.status_code == 200
        reopened = response.json()
        assert reopened == {
            **approved,
            "status": "draft",
            "revision": 4,
            "approved_at": None,
            "approved_by": None,
        }
        for field in ("notes", "sections", "status", "revision"):
            assert reopened[field] == example[field]
        assert {
            field: reopened["metadata"][field] for field in example["metadata"]
        } == example["metadata"]
        assert client.get(path).json() == reopened
        assert (
            client.get("/reports", params={"approved_by": "Taylor Example"}).json()
            == []
        )
        assert client.post(f"{path}/reopen", json={"revision": 4}).status_code == 409
        assert (
            client.post(f"/reports/{uuid4()}/reopen", json={"revision": 4}).status_code
            == 404
        )

        corrected = {**sections, "data": "Corrected session summary."}
        assert (
            client.patch(path, json={"revision": 3, "sections": corrected}).status_code
            == 409
        )
        saved_again = client.patch(path, json={"revision": 4, "sections": corrected})
        assert saved_again.status_code == 200
        assert saved_again.json()["revision"] == 5
        approved_again = client.post(
            f"{path}/approve", json={"revision": 5, "approved_by": "Jordan Example"}
        )
        assert approved_again.status_code == 200
        assert approved_again.json()["revision"] == 6
        assert approved_again.json()["approved_by"] == "Jordan Example"
        assert approved_again.json()["sections"] == corrected


def test_corrected_notes_and_regeneration_keep_the_same_draft(app, mock_ollama):
    """Keep saved edits on failure and replace notes and DAP together on retry."""
    manual_sections = {
        "data": "Staff recorded a breathing exercise.",
        "assessment": "Not documented.",
        "plan": "Not documented.",
    }
    corrected_notes = "The student practiced paced breathing."
    generated = {**manual_sections, "data": corrected_notes}
    requests = []

    def reply(request):
        requests.append(json.loads(request.content)["messages"][1]["content"])
        if len(requests) == 1:
            raise httpx.ConnectError("Ollama is offline.", request=request)
        return httpx.Response(
            200, json={"done": True, "message": {"content": json.dumps(generated)}}
        )

    mock_ollama(reply)
    with TestClient(app) as client:
        created = client.post("/reports/manual", json={"notes": NOTES})
        assert created.status_code == 201
        report_id = created.json()["report_id"]
        path = f"/reports/{report_id}"
        saved = client.patch(path, json={"revision": 1, "sections": manual_sections})
        assert saved.status_code == 200

        correction = client.patch(
            path, json={"revision": 2, "notes": "The student practiced breathing."}
        )
        assert correction.status_code == 200
        corrected = correction.json()
        assert corrected == {
            **saved.json(),
            "notes": "The student practiced breathing.",
            "revision": 3,
        }

        payload = {"revision": 3, "notes": corrected_notes, "metadata": {"grade": "8"}}
        regenerate = f"{path}/regenerate"
        assert (
            client.post(regenerate, json={**payload, "revision": 2}).status_code == 409
        )
        assert (
            client.post(regenerate, json={**payload, "notes": " "}).status_code == 422
        )
        assert (
            client.post(f"/reports/{uuid4()}/regenerate", json=payload).status_code
            == 404
        )
        assert requests == []

        assert client.post(regenerate, json=payload).status_code == 503
        assert client.get(path).json() == corrected
        response = client.post(regenerate, json=payload)
        assert response.status_code == 200
        updated = response.json()
        assert updated == {
            **corrected,
            "notes": corrected_notes,
            "sections": generated,
            "metadata": {
                **corrected["metadata"],
                "grade": "8",
                "draft_source": "ai_assisted",
            },
            "revision": 4,
        }
        assert client.get(path).json() == updated
        assert [report["report_id"] for report in client.get("/reports").json()] == [
            report_id
        ]

        approval = client.post(
            f"{path}/approve", json={"revision": 4, "approved_by": "Taylor Example"}
        )
        assert approval.status_code == 200
        assert (
            client.post(regenerate, json={**payload, "revision": 5}).status_code == 409
        )
        assert (
            client.patch(
                path, json={"revision": 5, "notes": corrected_notes}
            ).status_code
            == 409
        )
        assert requests == [corrected_notes, corrected_notes]


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
        "student_name": "Eva Synthetic",
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
            ({"student_name": "eVA"}, [first_id]),
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


def test_reversed_session_times_are_rejected_without_saving(app, mock_ollama):
    """Check new and partial edits, including AI requests before inference."""

    def unexpected_request(_request):
        pytest.fail("Reversed times should be rejected before calling Ollama.")

    mock_ollama(unexpected_request)
    times = {"start_time": "09:00", "end_time": "09:25"}
    error = {"detail": "End time must be at or after start time."}
    with TestClient(app) as client:
        for route in ("manual", "generate"):
            response = client.post(
                f"/reports/{route}",
                json={"notes": NOTES, "metadata": {**times, "end_time": "08:55"}},
            )
            assert response.status_code == 422
            assert response.json() == error
        assert client.get("/reports").json() == []

        created = client.post("/reports/manual", json={"metadata": times})
        assert created.status_code == 201
        draft = created.json()
        path = f"/reports/{draft['report_id']}"
        edit = {"revision": draft["revision"], "metadata": {"start_time": "10:00"}}
        for response in (
            client.patch(path, json=edit),
            client.post(f"{path}/regenerate", json={**edit, "notes": NOTES}),
        ):
            assert response.status_code == 422
            assert response.json() == error
        assert client.get(path).json() == draft

        cleared = client.patch(
            path, json={**edit, "metadata": {**edit["metadata"], "end_time": None}}
        )
        assert cleared.status_code == 200
        assert cleared.json()["metadata"]["end_time"] is None
        assert cleared.json()["metadata"]["total_minutes"] is None


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


@pytest.mark.parametrize(
    ("method", "suffix", "payload"),
    [
        ("PATCH", "", {"revision": 1, "notes": "Synthetic correction."}),
        ("POST", "/approve", {"revision": 1, "approved_by": "Taylor Example"}),
    ],
    ids=["edit", "approve"],
)
def test_missing_report_actions_return_404_without_changing_storage(
    app, method, suffix, payload
):
    """A valid action on an unknown UUID must not create or modify a report."""
    with TestClient(app) as client:
        saved = (
            client.post("/reports/manual", json={"notes": NOTES})
            .raise_for_status()
            .json()
        )
        history_before = client.get("/reports").raise_for_status().json()
        missing_path = f"/reports/{uuid4()}"

        response = client.request(method, f"{missing_path}{suffix}", json=payload)

        assert response.status_code == 404
        assert response.json() == {"detail": "Report draft not found."}
        assert client.get(missing_path).status_code == 404
        assert client.get("/reports").raise_for_status().json() == history_before
        assert (
            client.get(f"/reports/{saved['report_id']}").raise_for_status().json()
            == saved
        )


def test_blank_notes_never_reach_ollama(app, mock_ollama):
    """Verify request validation rejects blank notes before generation."""

    def unexpected_call(request):
        """Fail if invalid input reaches the Ollama client."""
        pytest.fail("Blank notes should be rejected before calling Ollama")

    mock_ollama(unexpected_call)
    with TestClient(app) as client:
        assert client.post("/reports/generate", json={"notes": "  "}).status_code == 422
        assert client.post("/reports/generate", json={}).status_code == 422


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


@pytest.mark.parametrize("operation", ["edit", "delete"])
def test_regeneration_cannot_overwrite_a_concurrent_report_change(
    app, mock_ollama, operation
):
    """Change storage while Ollama is working and reject its outdated result."""
    generating = Event()
    finish_generation = Event()
    generated_sections = {
        "data": "Generated text from the outdated source notes.",
        "assessment": "Not documented.",
        "plan": "Not documented.",
    }

    async def delayed_reply(request):
        """Hold the AI reply until another request has modified the report."""
        generating.set()
        assert await asyncio.to_thread(finish_generation.wait, timeout=10), (
            "The competing request did not finish."
        )
        return httpx.Response(
            200,
            json={"done": True, "message": {"content": json.dumps(generated_sections)}},
        )

    mock_ollama(delayed_reply)
    with TestClient(app) as client:
        initial = (
            client.post(
                "/reports/manual",
                json={"notes": NOTES, "metadata": {"student_name": "Alex Example"}},
            )
            .raise_for_status()
            .json()
        )
        path = f"/reports/{initial['report_id']}"

        with ThreadPoolExecutor(max_workers=1) as executor:
            regeneration = executor.submit(
                client.post,
                f"{path}/regenerate",
                json={
                    "revision": initial["revision"],
                    "notes": "Outdated revised notes.",
                    "metadata": {"student_name": "Outdated name"},
                },
            )
            try:
                assert generating.wait(timeout=10), "Regeneration never reached Ollama."
                if operation == "edit":
                    latest = (
                        client.patch(
                            path,
                            json={
                                "revision": initial["revision"],
                                "notes": "Newer notes saved by another user.",
                                "sections": {
                                    **initial["sections"],
                                    "data": "Newer observation.",
                                },
                                "metadata": {"student_name": "Updated Example"},
                            },
                        )
                        .raise_for_status()
                        .json()
                    )
                else:
                    deleted = client.delete(
                        path, params={"revision": initial["revision"]}
                    )
                    assert deleted.status_code == 204
            finally:
                finish_generation.set()
            response = regeneration.result(timeout=10)

        if operation == "edit":
            assert response.status_code == 409
            assert (
                response.json()["detail"]
                == "Report changed. Reload the current revision."
            )
            assert client.get(path).raise_for_status().json() == latest
            assert latest["revision"] == initial["revision"] + 1
            assert latest["metadata"]["draft_source"] == "handwritten"
            history = client.get("/reports").raise_for_status().json()
            assert [report["report_id"] for report in history] == [initial["report_id"]]
        else:
            assert response.status_code == 404
            assert response.json()["detail"] == "Report draft not found."
            assert client.get(path).status_code == 404
            assert client.get("/reports").raise_for_status().json() == []
