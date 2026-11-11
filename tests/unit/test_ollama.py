"""Test Ollama reply parsing without a running model server."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from documentation_assistant.backend.llm.ollama import (
    InvalidModelResponse,
    generate_dap,
)

NOTES = "Synthetic student practiced a breathing exercise."
SECTIONS = {"data": NOTES, "assessment": "Not documented.", "plan": "Not documented."}


@pytest.fixture
def ollama_post(monkeypatch):
    """Provide a mock POST method for the async HTTP client."""
    client = MagicMock()
    post = AsyncMock()
    # The client is entered with async with before calling post().
    client.__aenter__.return_value.post = post
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    return post


def test_generate_dap_parses_completed_reply(ollama_post):
    """Verify a completed reply becomes validated DAP sections."""
    ollama_post.return_value = httpx.Response(
        200,
        request=httpx.Request("POST", "http://127.0.0.1:11434/api/chat"),
        json={"done": True, "message": {"content": json.dumps(SECTIONS)}},
    )

    sections = asyncio.run(generate_dap(NOTES))

    assert sections.model_dump() == SECTIONS
    ollama_post.assert_awaited_once()


@pytest.mark.parametrize(
    ("notes", "plan", "evidence", "expected"),
    [
        (
            "The student said they felt nervous before a math test. "
            "We practiced paced breathing together.",
            "Staff will offer paced breathing before future tests. "
            "No further action is planned.",
            [],
            "Not documented.",
        ),
        (
            f"{NOTES} We agree on a plan tomorrow to meet after school to follow up.",
            "A follow-up meeting is planned for after school tomorrow.",
            ["We agree on a plan tomorrow to meet after school to follow up."],
            "A follow-up meeting is planned for after school tomorrow.",
        ),
        (
            f"{NOTES}\nThe student and social worker will meet Friday\n after lunch.",
            "The student and social worker will check in Friday after lunch.",
            ["The student and social worker will meet Friday after lunch."],
            "The student and social worker will check in Friday after lunch.",
        ),
        (
            NOTES,
            "A follow-up is planned for Friday.",
            ["The social worker will follow up Friday."],
            "Not documented.",
        ),
    ],
    ids=[
        "missing-evidence",
        "matching-evidence",
        "wrapped-evidence",
        "invented-evidence",
    ],
)
def test_generate_dap_requires_plan_evidence_from_notes(
    ollama_post, notes, plan, evidence, expected
):
    """Keep the plan only when its evidence appears in the notes."""
    ollama_post.return_value = httpx.Response(
        200,
        request=httpx.Request("POST", "http://127.0.0.1:11434/api/chat"),
        json={
            "done": True,
            "message": {
                "content": json.dumps(
                    {**SECTIONS, "plan": plan, "plan_evidence": evidence}
                )
            },
        },
    )

    assert asyncio.run(generate_dap(notes)).model_dump() == {
        **SECTIONS,
        "plan": expected,
    }


@pytest.mark.parametrize(
    "reply",
    [
        {"done": False, "message": {"content": json.dumps(SECTIONS)}},
        {
            "done": True,
            "done_reason": "length",
            "message": {"content": json.dumps(SECTIONS)},
        },
        {"done": True, "message": {"content": "invalid JSON"}},
        {"done": True, "message": {"content": json.dumps({"data": NOTES})}},
        {"done": True, "message": {}},
    ],
    ids=[
        "unfinished",
        "truncated",
        "invalid-json",
        "missing-sections",
        "missing-content",
    ],
)
def test_generate_dap_rejects_unusable_replies(ollama_post, reply):
    """Verify incomplete or malformed replies raise InvalidModelResponse."""
    ollama_post.return_value = httpx.Response(
        200,
        request=httpx.Request("POST", "http://127.0.0.1:11434/api/chat"),
        json=reply,
    )

    with pytest.raises(InvalidModelResponse):
        asyncio.run(generate_dap(NOTES))
