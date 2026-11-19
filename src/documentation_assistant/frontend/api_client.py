"""Send report requests to FastAPI and check local Ollama reachability."""

import os

import httpx
import streamlit as st

API_URL = os.getenv("DAP_API_URL", "http://127.0.0.1:8000").rstrip("/")


def ollama_is_reachable():
    """Return whether local Ollama responds with a model list, even if empty."""
    try:
        # Bypass proxy settings for the loopback request.
        response = httpx.get(
            "http://127.0.0.1:11434/api/tags", timeout=3, trust_env=False
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return False
    return isinstance(payload, dict) and isinstance(payload.get("models"), list)


def request_api(method, path, *, payload=None, params=None, timeout=10, raw=False):
    """Send a FastAPI request and show an error in Streamlit if it fails.

    Return decoded JSON by default, the HTTP response when raw is True, or
    True for a 204 response in JSON mode. Return None for HTTP errors,
    connection errors, or invalid JSON responses.
    """
    try:
        response = httpx.request(
            method, f"{API_URL}{path}", json=payload, params=params, timeout=timeout
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        message = (
            f"The server could not complete the request ({exc.response.status_code})."
        )
        # These responses explain a report conflict or a generation failure.
        if exc.response.status_code in (409, 502, 503, 504):
            try:
                body = exc.response.json()
            except ValueError:
                body = None
            detail = body.get("detail") if isinstance(body, dict) else None
            if isinstance(detail, str) and detail.strip():
                message = detail
        st.error(message)
        return None
    except httpx.RequestError:
        st.error("Could not reach the report server. Check that FastAPI is running.")
        return None
    if raw:
        return response
    if response.status_code == 204:
        return True
    try:
        return response.json()
    except ValueError:
        st.error("The report server returned an invalid JSON response. Try again.")
        return None
