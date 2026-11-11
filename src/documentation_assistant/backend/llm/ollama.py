"""Send synthetic notes to the local Ollama server and validate its reply."""

import os
from pathlib import Path

import httpx
from pydantic import Field

from documentation_assistant.backend.schemas.reports import DAPSections, NonBlankText

_PROMPT = (Path(__file__).parent / "prompts" / "dap_generation.txt").read_text(
    encoding="utf-8"
)
_NOT_DOCUMENTED = "Not documented."


class OllamaDraft(DAPSections):
    """Keep supporting excerpts separate from the polished report text."""

    plan_evidence: list[NonBlankText] = Field(default_factory=list)


class InvalidModelResponse(Exception):
    """Ollama returned an incomplete or invalid draft."""


async def generate_dap(notes: str) -> DAPSections:
    """Generate and validate DAP sections from synthetic session notes."""
    # Bypass environment proxy settings for the local Ollama request.
    async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
        response = await client.post(
            "http://127.0.0.1:11434/api/chat",
            json={
                "model": os.getenv("OLLAMA_MODEL", "qwen3:8b"),
                "stream": False,
                "think": False,
                # Use the same schema for generation and response validation.
                "format": OllamaDraft.model_json_schema(),
                "messages": [
                    {"role": "system", "content": _PROMPT},
                    {"role": "user", "content": notes},
                ],
                "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 1200},
            },
        )
        response.raise_for_status()

    try:
        result = response.json()
        # A finished request can still contain a draft cut off at the token limit.
        if result["done"] is not True or result.get("done_reason") == "length":
            raise InvalidModelResponse("The model did not complete the draft.")
        draft = OllamaDraft.model_validate_json(result["message"]["content"])
    except (ValueError, KeyError, TypeError) as exc:
        raise InvalidModelResponse("The model returned an invalid draft.") from exc

    # Verify the evidence without requiring the displayed Plan to quote the notes.
    has_plan_evidence = bool(draft.plan_evidence) and all(
        excerpt in notes for excerpt in draft.plan_evidence
    )
    return DAPSections(
        data=draft.data,
        assessment=draft.assessment,
        plan=draft.plan if has_plan_evidence else _NOT_DOCUMENTED,
    )
