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
    client = MagicMock()
    post = AsyncMock()
    client.__aenter__.return_value.post = post
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    return post


def test_generate_dap_parses_completed_reply(ollama_post):
    ollama_post.return_value = httpx.Response(
        200,
        request=httpx.Request("POST", "http://127.0.0.1:11434/api/chat"),
        json={"done": True, "message": {"content": json.dumps(SECTIONS)}},
    )

    sections = asyncio.run(generate_dap(NOTES))

    assert sections.model_dump() == SECTIONS
    ollama_post.assert_awaited_once()


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
    ollama_post.return_value = httpx.Response(
        200,
        request=httpx.Request("POST", "http://127.0.0.1:11434/api/chat"),
        json=reply,
    )

    with pytest.raises(InvalidModelResponse):
        asyncio.run(generate_dap(NOTES))
