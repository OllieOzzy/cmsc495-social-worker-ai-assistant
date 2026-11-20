"""Send report requests to FastAPI and check local Ollama reachability."""

import os
from ipaddress import ip_address
from urllib.parse import urlsplit

import httpx
import streamlit as st

API_URL = os.getenv("DAP_API_URL", "http://127.0.0.1:8000").rstrip("/")


@st.cache_resource(
    scope="session", show_spinner=False, on_release=lambda client: client.close()
)
def _get_http_client(trust_env: bool = True) -> httpx.Client:
    """Reuse a client within one browser session and close it on cache release.

    Requests with the same proxy policy share a client within the session.
    Only clients are cached; each action still sends a fresh request.
    """
    return httpx.Client(trust_env=trust_env)


def _is_loopback_url(url: str) -> bool:
    """Recognize localhost and literal loopback IPs without resolving remote names."""
    hostname = urlsplit(url).hostname
    if hostname and hostname.rstrip(".") == "localhost":
        return True
    try:
        return ip_address(hostname).is_loopback
    except ValueError:
        return False


def ollama_is_reachable():
    """Return whether local Ollama responds with a model list, even if empty."""
    try:
        # Bypass proxy settings for the loopback request.
        response = _get_http_client(trust_env=False).get(
            "http://127.0.0.1:11434/api/tags", timeout=3
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return False
    return isinstance(payload, dict) and isinstance(payload.get("models"), list)


def _validation_message(detail: list) -> str | None:
    """Format FastAPI field errors without displaying submitted input or context."""
    messages = []
    for error in detail:
        if not isinstance(error, dict):
            continue
        message = error.get("msg")
        if not isinstance(message, str) or not message.strip():
            continue
        message = message.strip()
        location = error.get("loc")
        if (
            isinstance(location, list)
            and location
            and isinstance(location[-1], str)
            and location[-1] not in ("body", "query", "path")
        ):
            field = location[-1].replace("_", " ").capitalize()
            message = f"{field}: {message}"
        if message not in messages:
            messages.append(message)
    return "\n\n".join(messages) or None


def request_api(method, path, *, payload=None, params=None, timeout=10, raw=False):
    """Send a FastAPI request and show an error in Streamlit if it fails.

    Return decoded JSON by default, the HTTP response when raw is True, or
    True for a 204 response in JSON mode. Return None for HTTP errors,
    connection errors, or invalid JSON responses.
    """
    try:
        # Loopback traffic stays on this computer. Remote backends retain
        # environment proxy and certificate settings, including NO_PROXY.
        response = _get_http_client(trust_env=not _is_loopback_url(API_URL)).request(
            method, f"{API_URL}{path}", json=payload, params=params, timeout=timeout
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        message = (
            f"The server could not complete the request ({exc.response.status_code})."
        )
        # Preserve actionable validation, report conflict, and generation errors.
        if exc.response.status_code in (409, 422, 502, 503, 504):
            try:
                body = exc.response.json()
            except ValueError:
                body = None
            detail = body.get("detail") if isinstance(body, dict) else None
            if isinstance(detail, str) and detail.strip():
                message = detail
            elif exc.response.status_code == 422 and isinstance(detail, list):
                message = _validation_message(detail) or message
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
