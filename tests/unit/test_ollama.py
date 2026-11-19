"""Test Ollama reply parsing with a mock application-owned async client.

Real HTTPX responses exercise status handling and JSON decoding without a
model server. Integration tests cover pooled-client startup and shutdown.
"""

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
def ollama_post():
    """Provide a mock POST method for the async HTTP client."""
    return AsyncMock()


@pytest.fixture
def ollama_client(ollama_post):
    """Provide the application-owned client used by generation."""
    return MagicMock(post=ollama_post)


def test_generate_dap_parses_completed_reply(ollama_post, ollama_client):
    """Verify a completed reply becomes validated DAP sections."""
    notes = f"{NOTES} We agreed to meet Friday after lunch."
    expected_sections = {
        **SECTIONS,
        "plan": "A check-in is planned for Friday after lunch.",
    }
    ollama_post.return_value = httpx.Response(
        200,
        request=httpx.Request("POST", "http://127.0.0.1:11434/api/chat"),
        json={"done": True, "message": {"content": json.dumps(expected_sections)}},
    )

    sections = asyncio.run(generate_dap(notes, ollama_client))

    assert sections.model_dump() == expected_sections
    ollama_client.aclose.assert_not_called()
    ollama_post.assert_awaited_once()
    assert set(ollama_post.call_args.kwargs["json"]["format"]["properties"]) == set(
        expected_sections
    )


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
def test_generate_dap_rejects_unusable_replies(ollama_post, ollama_client, reply):
    """Verify incomplete or malformed replies raise InvalidModelResponse."""
    ollama_post.return_value = httpx.Response(
        200,
        request=httpx.Request("POST", "http://127.0.0.1:11434/api/chat"),
        json=reply,
    )

    with pytest.raises(InvalidModelResponse):
        asyncio.run(generate_dap(NOTES, ollama_client))
