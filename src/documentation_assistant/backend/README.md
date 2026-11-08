# FastAPI Backend

The backend currently provides an application entry point, a health endpoint,
and interactive API documentation. Session processing, Ollama integration,
database storage, and PDF export.

## Local Setup

Run all commands in this guide from the **repository root**, which contains
`requirements.txt` and `pyproject.toml`.

For a first-time setup on Windows, create a Python 3.12 virtual environment:

```powershell
py -3.12 -m venv .venv
```

Activate the environment and install dependencies:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Start the Server

```powershell
python -m uvicorn documentation_assistant.backend.main:app --app-dir src --host 127.0.0.1 --port 8000 --reload
```

The server listens locally on port 8000. The `--reload` option restarts the
development server after code changes. Press Ctrl+C to stop it.
Change `--port` if another application is using port 8000.

## Available Endpoints

| Endpoint | Purpose |
| --- | --- |
| [GET /health](http://127.0.0.1:8000/health) | Confirms the backend is responding. |
| [GET /docs](http://127.0.0.1:8000/docs) | Interactive API documentation. |
| [GET /openapi.json](http://127.0.0.1:8000/openapi.json) | Machine-readable API schema. |

The health endpoint returns:

```json
{"status": "ok"}
```

This checks API liveness only. Ollama and database readiness checks will be added
with their integrations.

## Tests

Run the backend integration tests:

```powershell
python -m pytest tests/integration/test_health_api.py -v
```
