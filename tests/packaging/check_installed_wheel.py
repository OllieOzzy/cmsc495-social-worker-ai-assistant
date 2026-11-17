"""Verify the launcher and handwritten report workflow from an installed wheel.

CI runs this script directly after installing the wheel.
"""

import os
import signal
import subprocess
import sys
from contextlib import suppress
from importlib.resources import files
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep

import httpx
from pypdf import PdfReader
from streamlit.testing.v1 import AppTest

_BACKEND_URL = "http://127.0.0.1:8000"
_FRONTEND_HEALTH_URL = "http://127.0.0.1:8501/_stcore/health"
_NOTES = "Synthetic session notes for the wheel check."
_DATA = "The student practiced asking for help."


def wait_for_servers(process: subprocess.Popen, client: httpx.Client) -> None:
    """Wait for both installed servers to answer their health endpoints."""
    deadline = monotonic() + 45
    while monotonic() < deadline:
        if (exit_code := process.poll()) is not None:
            raise RuntimeError(f"dap-assistant exited during startup ({exit_code}).")
        try:
            frontend = client.get(_FRONTEND_HEALTH_URL)
            backend = client.get(f"{_BACKEND_URL}/health")
            if frontend.is_success and backend.json() == {"status": "ok"}:
                return
        except (httpx.RequestError, ValueError):
            pass
        sleep(0.25)
    raise RuntimeError("FastAPI and Streamlit did not become ready within 45 seconds.")


def check_handwritten_report(client: httpx.Client) -> None:
    """Save a draft through the installed Streamlit form and read its PDF."""
    app_path = files("documentation_assistant.frontend").joinpath("app.py")
    app = AppTest.from_file(str(app_path), default_timeout=20).run()
    assert not app.exception, app.exception

    notes = next(field for field in app.text_area if "Session Notes" in field.label)
    notes.set_value(_NOTES)
    next(button for button in app.button if button.label == "Written by hand").click()
    app.run()
    assert not app.exception, app.exception

    report_id = app.session_state["report"]["report_id"]
    data = next(field for field in app.text_area if field.label.startswith("D: Data"))
    data.set_value(_DATA)
    next(button for button in app.button if button.label == "Save draft").click()
    app.run()
    assert not app.exception, app.exception

    report_url = f"{_BACKEND_URL}/reports/{report_id}"
    saved = client.get(report_url).raise_for_status().json()
    assert saved["notes"] == _NOTES
    assert saved["sections"]["data"] == _DATA
    response = client.get(f"{report_url}/download").raise_for_status()
    assert response.headers["content-type"] == "application/pdf"
    pdf = PdfReader(BytesIO(response.content), strict=True)
    assert _DATA in pdf.pages[0].extract_text()


def stop_launcher(process: subprocess.Popen) -> None:
    """Stop the launcher and its server processes after the check."""
    if os.name == "nt":
        if process.poll() is None:
            subprocess.run(
                ["taskkill", "/pid", str(process.pid), "/t", "/f"],
                capture_output=True,
                check=False,
                timeout=10,
            )
        venv_python = str(Path(sys.executable).resolve()).replace("'", "''")
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"Get-CimInstance Win32_Process -Filter \"Name = 'python.exe'\" | "
                f"Where-Object {{ $_.ExecutablePath -eq '{venv_python}' -and $_.ProcessId -ne {os.getpid()} }} | "
                f"ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }}",
            ],
            capture_output=True,
            check=False,
            timeout=10,
        )
        process.wait(timeout=10)
        sleep(0.2)
    else:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=10)


def main() -> None:
    """Start the installed command from a temporary directory with a fresh database."""
    windows = os.name == "nt"
    command = Path(sys.executable).with_name(
        "dap-assistant.exe" if windows else "dap-assistant"
    )
    os.environ["DAP_API_URL"] = _BACKEND_URL
    with TemporaryDirectory(prefix="dap-wheel-") as directory:
        workdir = Path(directory)
        env = {
            **os.environ,
            "DAP_DB_PATH": str(workdir / "reports.db"),
            "STREAMLIT_SERVER_HEADLESS": "true",
            "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
        }
        env.pop("PYTHONPATH", None)
        log_path = workdir / "launcher.log"
        with log_path.open("wb") as log:
            process = subprocess.Popen(
                [str(command)],
                cwd=workdir,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if windows else 0,
                start_new_session=not windows,
            )
            try:
                with httpx.Client(timeout=5, trust_env=False) as client:
                    wait_for_servers(process, client)
                    check_handwritten_report(client)
            except Exception:
                print(log_path.read_text(encoding="utf-8", errors="replace"))
                raise
            finally:
                stop_launcher(process)
    print(
        "Installed dap-assistant started both servers, saved a draft, and exported a PDF."
    )


if __name__ == "__main__":
    main()
