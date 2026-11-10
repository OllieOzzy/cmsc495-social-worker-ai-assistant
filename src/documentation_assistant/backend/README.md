# FastAPI Backend

The backend currently provides an application entry point, a health endpoint,
interactive API documentation, and DAP draft generation through local Ollama.
SQLite stores the source notes and generated drafts.

## Local Setup

Run all commands in this guide from the **repository root**, which contains
`requirements.txt` and `pyproject.toml`.

Use Python 3.12. Create and activate a virtual environment for your platform.

**Windows (PowerShell)**

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS and Linux (bash or zsh)**

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

With the environment active, install the dependencies:

```bash
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
| `POST /reports/generate` | Generates and saves an unapproved DAP draft from synthetic notes. |
| `GET /reports` | Lists saved draft summaries, newest saved first. |
| `GET /reports/{report_id}` | Retrieves a saved draft and its source notes. |

The health endpoint returns:

```json
{"status": "ok"}
```

This checks API liveness and works independently of Ollama.

## Generate a Draft

Start Ollama and run `ollama pull qwen3:8b` if the model is missing. The backend
uses Ollama on `127.0.0.1:11434`. To use a different installed model, set
`OLLAMA_MODEL` before starting the backend.

- PowerShell: `$env:OLLAMA_MODEL = "your-model-tag"`
- bash or zsh: `export OLLAMA_MODEL="your-model-tag"`

In `/docs`, open **POST /reports/generate**, select **Try it out**, and submit:

```json
{"notes": "Synthetic student practiced a breathing exercise and reported feeling calmer afterward."}
```

The response has a `report_id`, a `draft` status, and `data`, `assessment`, and
`plan` under `sections`. Use the ID in **GET /reports/{report_id}** to retrieve
the draft alongside its source notes, including after restarting the backend.
Retrieval works with Ollama stopped. Review the content against the source
notes. Schema validation checks the response structure, while the reviewer
checks factual accuracy.

SQLite creates `data/dap.db` on first use of draft storage when the
backend starts from the repository root. To use another location, set
`DAP_DB_PATH` before starting the backend. Use synthetic notes only.

Use `GET /reports` to find a saved draft without already knowing its ID. Each
summary contains `report_id`, `status`, and a UTC `created_at` timestamp.
Drafts saved before timestamps were introduced have `created_at: null`.

## Tests

Run the full test suite, including unit and integration tests:

```powershell
python -m pytest
```
