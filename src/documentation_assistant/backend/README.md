# FastAPI Backend

The backend currently provides an application entry point, a health endpoint,
interactive API documentation, and DAP draft generation through local Ollama.
Database storage, approval, and PDF export are planned follow-up work.

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
| `POST /reports/generate` | Generates an unapproved DAP draft from synthetic notes. |

The health endpoint returns:

```json
{"status": "ok"}
```

This checks API liveness and works independently of Ollama.

## Generate a Draft

Start Ollama and run `ollama pull qwen3:8b` if the model is missing. The backend
uses Ollama on `127.0.0.1:11434`. To use a different installed model, set
`$env:OLLAMA_MODEL = "your-model-tag"` before starting the backend.

In `/docs`, open **POST /reports/generate**, select **Try it out**, and submit:

```json
{"notes": "Synthetic student practiced a breathing exercise and reported feeling calmer afterward."}
```

The response has a `draft` status and `data`, `assessment`, and `plan` under
`sections`. Review the content against the source notes. Schema validation checks
the response structure, while the reviewer checks factual accuracy.

## Tests

Run the backend integration tests:

```powershell
python -m pytest tests/integration/test_health_api.py tests/integration/test_reports_api.py -v
```
