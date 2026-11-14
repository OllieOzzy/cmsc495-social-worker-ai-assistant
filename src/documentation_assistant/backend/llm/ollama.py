"""Request and validate structured DAP drafts from the local Ollama server."""

import os
from pathlib import Path

import httpx

from documentation_assistant.backend.schemas.reports import DAPSections

# Load the prompt once when the backend imports this module.
_PROMPT = (Path(__file__).parent / "prompts" / "dap_generation.txt").read_text(
    encoding="utf-8"
)


class InvalidModelResponse(Exception):
    """Ollama returned an incomplete or invalid draft."""


async def generate_dap(notes: str) -> DAPSections:
    """Generate three nonblank DAP sections from synthetic session notes.

    Raise InvalidModelResponse if Ollama's reply is incomplete or malformed.
    The reviewer checks the draft's accuracy against the source notes.
    """
    # Connect directly to Ollama on loopback, bypassing proxy settings.
    async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
        response = await client.post(
            "http://127.0.0.1:11434/api/chat",
            json={
                "model": os.getenv("OLLAMA_MODEL", "qwen3:8b"),
                "stream": False,
                "think": False,
                # Ask Ollama for the same three-field structure the backend validates.
                "format": DAPSections.model_json_schema(),
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
        # A reply marked done can still be truncated at the output token limit.
        if result["done"] is not True or result.get("done_reason") == "length":
            raise InvalidModelResponse("The model did not complete the draft.")
        return DAPSections.model_validate_json(result["message"]["content"])
    except (ValueError, KeyError, TypeError) as exc:
        raise InvalidModelResponse("The model returned an invalid draft.") from exc
