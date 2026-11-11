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
| `POST /reports/manual` | Saves source notes and opens a draft with blank DAP sections. |
| `GET /reports` | Lists and filters saved report summaries, newest saved first. |
| `GET /reports/{report_id}` | Retrieves a saved report, its source notes, and its review state. |
| `PATCH /reports/{report_id}` | Saves corrected DAP sections or report details on a draft. |
| `POST /reports/{report_id}/approve` | Approves the saved revision and makes it read-only. |

The health endpoint returns:

```json
{"status": "ok"}
```

This checks API liveness and works independently of Ollama.

## Start a Draft

For manual writing, send the notes and optional metadata to
`POST /reports/manual`. The response contains the saved notes and blank
DAP sections. You can save a draft while sections are still blank and
approve it after all three contain text. This workflow works with Ollama
stopped.

For AI-assisted writing, use `POST /reports/generate`. The API records the
draft source based on the endpoint used.

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
When generating a draft, you can include a `metadata` object with
`student_name`, `student_id`, `school`, `grade`, `date_of_service`, and
`social_worker_name`.
Use a string for grade and `YYYY-MM-DD` for dates.

Filter the list with any combination of `student_name` and
`social_worker_name` (partial, case-insensitive matches),
`student_id`, `school`, `grade`, `date_from`, and `date_to`. The date range
is inclusive and uses date of service. Drafts with missing values remain in
the unfiltered list.

Use `status=draft` or `status=approved` to show one status. Omit `status`
to show both. Use `approved_by` to search the recorded approver's name by
partial, case-insensitive match.

## Review and Approve

Open the report by ID to get its current `revision`. To save changes, send
that revision and DAP `sections`, `metadata`, or both to `PATCH /reports/{report_id}`.
Include all three DAP fields when replacing `sections`. Within `metadata`,
include only the fields to change. Use `null` to clear an optional detail.
The response contains the new revision and the source notes. The report stays
in draft status. When review is complete, send the revision you reviewed
and the reviewer's name to `POST /reports/{report_id}/approve`.

```json
{"revision": 2, "approved_by": "Taylor Example"}
```

Approval records the supplied name and a UTC `approved_at` timestamp. An approved report or a
stale revision returns `409` on a review action. Reload the report before
trying again. Editing and approval work with Ollama stopped.

## Tests

Run the full test suite, including unit and integration tests:

```powershell
python -m pytest
```
