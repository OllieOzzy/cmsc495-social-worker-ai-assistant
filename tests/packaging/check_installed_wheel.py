"""Verify the launcher and handwritten report workflow from an installed wheel.

CI runs this script directly with Python's -I option after installing the wheel
in a fresh environment. It is not a pytest test: it starts real server processes
and uses AppTest on the installed frontend, without requiring Ollama.
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
    """Verify installed login, owner edits, admin approval, PDF export, and logout."""
    assert client.get(f"{_BACKEND_URL}/reports").status_code == 401
    app_path = files("documentation_assistant.frontend").joinpath("app.py")
    app = AppTest.from_file(str(app_path), default_timeout=20).run()
    assert not app.exception, app.exception

    app.text_input(key="login_username").set_value("user")
    app.text_input(key="login_password").set_value("password1234")
    next(button for button in app.button if button.label == "Sign in").click()
    app.run()
    assert not app.exception, app.exception

    assert app.session_state["auth_user"]["role"] == "user"
    assert all(button.label != "Approve saved draft" for button in app.button)

    notes = next(field for field in app.text_area if "Session Notes" in field.label)
    notes.set_value(_NOTES)
    next(button for button in app.button if button.label == "Written by hand").click()
    app.run()
    assert not app.exception, app.exception

    report_id = app.session_state["report"]["report_id"]
    data = next(field for field in app.text_area if field.label.startswith("D: Data"))
    data.set_value(_DATA)
    for label in ("A: Assessment", "P: Plan"):
        next(
            field for field in app.text_area if field.label.startswith(label)
        ).set_value("Not documented.")
    next(button for button in app.button if button.label == "Save draft").click()
    app.run()
    assert not app.exception, app.exception

    report_url = f"{_BACKEND_URL}/reports/{report_id}"
    headers = {"Authorization": f"Bearer {app.session_state['auth_token']}"}
    saved = client.get(report_url, headers=headers).raise_for_status().json()
    assert saved["owner_id"] == app.session_state["auth_user"]["user_id"]
    assert saved["notes"] == _NOTES
    assert saved["sections"]["data"] == _DATA
    response = client.get(f"{report_url}/download", headers=headers).raise_for_status()
    assert response.headers["content-type"] == "application/pdf"
    # Read the exported content to verify the packaged template and saved DAP text.
    pdf = PdfReader(BytesIO(response.content), strict=True)
    assert _DATA in pdf.pages[0].extract_text()

    # Regular users cannot approve, including when they own the report.
    assert (
        client.post(
            f"{report_url}/approve",
            json={"revision": saved["revision"]},
            headers=headers,
        ).status_code
        == 403
    )
    assert client.get(f"{_BACKEND_URL}/users", headers=headers).status_code == 403
    admin = (
        client.post(
            f"{_BACKEND_URL}/auth/login",
            json={"username": "admin", "password": "password1234"},
        )
        .raise_for_status()
        .json()
    )
    admin_headers = {"Authorization": f"Bearer {admin['access_token']}"}
    accounts = (
        client.get(f"{_BACKEND_URL}/users", headers=admin_headers)
        .raise_for_status()
        .json()
    )
    assert {account["username"] for account in accounts} == {"admin", "user"}
    assert all("password_hash" not in account for account in accounts)
    approved = (
        client.post(
            f"{report_url}/approve",
            json={"revision": saved["revision"]},
            headers=admin_headers,
        )
        .raise_for_status()
        .json()
    )
    assert approved["approved_by"] == admin["user"]["display_name"]
    assert (
        client.delete(
            report_url, params={"revision": approved["revision"]}, headers=headers
        ).status_code
        == 409
    )

    next(button for button in app.button if button.label == "Sign out").click()
    app.run()
    assert not app.exception, app.exception
    assert "report" not in app.session_state
    assert "auth_token" not in app.session_state
    assert client.get(report_url, headers=headers).status_code == 401
    # Password recovery works in the installed package without restoring old tokens.
    replacement = "Synthetic installed reset password!"
    client.post(
        f"{_BACKEND_URL}/users/{saved['owner_id']}/reset-password",
        json={"password": replacement},
        headers=admin_headers,
    ).raise_for_status()
    assert (
        client.post(
            f"{_BACKEND_URL}/auth/login",
            json={"username": "user", "password": "password1234"},
        ).status_code
        == 401
    )
    recovered = (
        client.post(
            f"{_BACKEND_URL}/auth/login",
            json={"username": "user", "password": replacement},
        )
        .raise_for_status()
        .json()
    )
    assert recovered["user"]["user_id"] == saved["owner_id"]
    assert client.get(report_url, headers=headers).status_code == 401
    changed_password = "Synthetic installed self-service password!"
    recovered_headers = {"Authorization": f"Bearer {recovered['access_token']}"}
    client.post(
        f"{_BACKEND_URL}/auth/change-password",
        json={"current_password": replacement, "new_password": changed_password},
        headers=recovered_headers,
    ).raise_for_status()
    assert (
        client.get(f"{_BACKEND_URL}/auth/me", headers=recovered_headers).status_code
        == 401
    )
    changed = (
        client.post(
            f"{_BACKEND_URL}/auth/login",
            json={"username": "user", "password": changed_password},
        )
        .raise_for_status()
        .json()
    )
    changed_headers = {"Authorization": f"Bearer {changed['access_token']}"}
    renamed = (
        client.patch(
            f"{_BACKEND_URL}/users/{saved['owner_id']}/profile",
            json={"username": "renamed-user", "display_name": "Renamed User"},
            headers=admin_headers,
        )
        .raise_for_status()
        .json()
    )
    assert renamed["user_id"] == saved["owner_id"]
    assert (
        client.get(f"{_BACKEND_URL}/auth/me", headers=changed_headers).status_code
        == 401
    )
    renamed_login = (
        client.post(
            f"{_BACKEND_URL}/auth/login",
            json={"username": "renamed-user", "password": changed_password},
        )
        .raise_for_status()
        .json()
    )
    assert (
        client.get(
            report_url,
            headers={"Authorization": f"Bearer {renamed_login['access_token']}"},
        ).status_code
        == 200
    )

    # Validate role management against the installed API, preserving report identity.
    promoted = (
        client.patch(
            f"{_BACKEND_URL}/users/{saved['owner_id']}/role",
            json={"role": "admin"},
            headers=admin_headers,
        )
        .raise_for_status()
        .json()
    )
    assert promoted["user_id"] == saved["owner_id"]
    assert promoted["role"] == "admin"
    assert (
        client.get(
            f"{_BACKEND_URL}/auth/me",
            headers={"Authorization": f"Bearer {renamed_login['access_token']}"},
        ).status_code
        == 401
    )
    fresh = (
        client.post(
            f"{_BACKEND_URL}/auth/login",
            json={"username": "renamed-user", "password": changed_password},
        )
        .raise_for_status()
        .json()
    )
    promoted_headers = {"Authorization": f"Bearer {fresh['access_token']}"}
    assert (
        client.get(f"{_BACKEND_URL}/users", headers=promoted_headers).status_code == 200
    )
    client.patch(
        f"{_BACKEND_URL}/users/{saved['owner_id']}/role",
        json={"role": "user"},
        headers=admin_headers,
    ).raise_for_status()
    assert (
        client.get(f"{_BACKEND_URL}/auth/me", headers=promoted_headers).status_code
        == 401
    )

    events_response = client.get(
        f"{_BACKEND_URL}/users/audit-events",
        params={"target_id": saved["owner_id"]},
        headers=admin_headers,
    ).raise_for_status()
    assert events_response.headers["cache-control"] == "no-store"
    actions = {event["action"] for event in events_response.json()}
    assert {
        "account_created",
        "password_reset",
        "password_changed",
        "account_renamed",
        "role_changed",
    } <= actions
    assert changed_password not in events_response.text
    assert "$argon2" not in events_response.text
    assert all("password" not in event["changes"] for event in events_response.json())
    assert client.get(f"{_BACKEND_URL}/users/audit-events").status_code == 401


def stop_launcher(process: subprocess.Popen) -> None:
    """Stop the launcher and its server processes after the check."""
    if os.name == "nt":
        # Terminate the process tree so Uvicorn and Streamlit do not survive the check.
        if process.poll() is None:
            subprocess.run(
                ["taskkill", "/pid", str(process.pid), "/t", "/f"],
                capture_output=True,
                check=False,
                timeout=10,
            )
        process.wait(timeout=10)
    else:
        # start_new_session gives the launcher and its children one process group.
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
        # The check must resolve installed packages, not import code from the checkout.
        env.pop("PYTHONPATH", None)
        # Provision only the temporary synthetic-data database used by this check.
        subprocess.run(
            [str(command), "init-demo-users"],
            cwd=workdir,
            env=env,
            check=True,
            timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if windows else 0,
        )
        # Keep launcher output in the CI log. On Windows, child processes can
        # keep an inherited log file open and block temporary directory cleanup.
        process = subprocess.Popen(
            [str(command)],
            cwd=workdir,
            env=env,
            stdout=sys.stdout,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if windows else 0,
            start_new_session=not windows,
        )
        try:
            with httpx.Client(timeout=5, trust_env=False) as client:
                wait_for_servers(process, client)
                check_handwritten_report(client)
        finally:
            stop_launcher(process)
    print(
        "Installed dap-assistant verified login, permissions, PDF export, account management, and credential-free audit history."
    )


if __name__ == "__main__":
    main()
