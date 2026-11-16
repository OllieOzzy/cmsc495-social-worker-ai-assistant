"""Run the local FastAPI and Streamlit servers with ``dap-assistant``.

Both servers listen on loopback. The launcher waits for FastAPI to become
ready before starting Streamlit and cleans up both processes on exit.
"""

import os
import socket
import subprocess
import sys
from pathlib import Path
from time import monotonic, sleep

import httpx

_HOST = "127.0.0.1"
_BACKEND_PORT = 8000
_FRONTEND_PORT = 8501
_BACKEND_URL = f"http://{_HOST}:{_BACKEND_PORT}"
# Resolve the Streamlit script relative to the installed package.
_FRONTEND_APP = Path(__file__).with_name("frontend") / "app.py"


def _check_ports() -> None:
    """Check that both loopback ports can be bound before starting the servers."""
    for port in (_BACKEND_PORT, _FRONTEND_PORT):
        with socket.socket() as probe:
            try:
                probe.bind((_HOST, port))
            except OSError as exc:
                raise RuntimeError(f"Port {port} is unavailable on {_HOST}.") from exc


def _wait_for_backend(backend: subprocess.Popen) -> None:
    """Poll FastAPI's health endpoint for up to 30 seconds.

    Raise RuntimeError if the process exits early or the health check times out.
    """
    deadline = monotonic() + 30
    # Send the loopback health check directly, bypassing environment proxies.
    with httpx.Client(timeout=1, trust_env=False) as client:
        while monotonic() < deadline:
            if (exit_code := backend.poll()) is not None:
                raise RuntimeError(f"FastAPI stopped during startup ({exit_code}).")
            try:
                response = client.get(f"{_BACKEND_URL}/health")
                if response.status_code == 200 and response.json() == {"status": "ok"}:
                    return
            except (httpx.RequestError, ValueError):
                # Retry when the local server is unreachable or returns invalid JSON.
                pass
            sleep(0.2)
    raise RuntimeError("FastAPI did not become ready within 30 seconds.")


def _stop_server(process: subprocess.Popen) -> None:
    """Terminate a running server and kill it if it stays up after five seconds."""
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def main() -> int:
    """Supervise both servers until Ctrl+C or either process exits.

    Return 0 for Ctrl+C or 1 for a startup failure or unexpected server exit.
    """
    servers: list[subprocess.Popen] = []
    try:
        _check_ports()
        # Run both servers with the same Python interpreter as the launcher.
        backend = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "documentation_assistant.backend.main:app",
                "--host",
                _HOST,
                "--port",
                str(_BACKEND_PORT),
            ]
        )
        servers.append(backend)
        _wait_for_backend(backend)

        # Point Streamlit to the backend started by this launcher.
        frontend = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(_FRONTEND_APP),
                "--server.address",
                _HOST,
                "--server.port",
                str(_FRONTEND_PORT),
            ],
            env={**os.environ, "DAP_API_URL": _BACKEND_URL},
        )
        servers.append(frontend)
        print(
            f"Open http://{_HOST}:{_FRONTEND_PORT}. Press Ctrl+C to stop.", flush=True
        )

        while True:
            for name, server in (("FastAPI", backend), ("Streamlit", frontend)):
                if (exit_code := server.poll()) is not None:
                    raise RuntimeError(f"{name} stopped ({exit_code}).")
            sleep(0.2)
    except KeyboardInterrupt:
        return 0
    except (OSError, RuntimeError) as exc:
        print(f"DAP Assistant: {exc}", file=sys.stderr)
        return 1
    finally:
        # Stop Streamlit first and also clean up after a partial startup.
        for server in reversed(servers):
            _stop_server(server)
