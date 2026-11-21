# FastAPI Backend

The FastAPI backend supports manual and AI-assisted DAP drafts, searchable
report history, review and approval, and PDF downloads. It saves source notes
and reports in SQLite and uses local Ollama for AI generation. Use synthetic
student data for development and testing.

## Overview Diagram

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 34, "rankSpacing": 42, "padding": 8, "curve": "step"}}}%%
flowchart TD
    UI["Streamlit frontend"]

    subgraph API["FastAPI backend"]
        Routes["Health and report routes<br/>Pydantic validation"]
        LLM["Ollama client<br/>DAP generation prompt"]
        Store["Report storage<br/>Revision and approval checks"]
        PDF["PDF renderer<br/>School DAP template"]

        Routes -->|"Generate or regenerate"| LLM
        Routes -->|"Save or load reports"| Store
        Routes -->|"Export"| PDF
        Store -->|"Saved report"| PDF
    end

    Ollama["Local Ollama"]
    SQLite[("SQLite<br/>data/dap.db by default")]

    UI <-->|"Requests, reports, and PDFs"| API
    LLM <-->|"POST /api/chat"| Ollama
    Store <--> SQLite

    classDef frontend fill:#DBEAFE,stroke:#2563EB,color:#1E3A8A
    classDef backend fill:#EDE9FE,stroke:#7C3AED,color:#4C1D95
    classDef ai fill:#CCFBF1,stroke:#0F766E,color:#134E4A
    classDef storage fill:#DCFCE7,stroke:#15803D,color:#14532D
    classDef export fill:#FEF3C7,stroke:#B45309,color:#78350F

    class UI frontend
    class Routes backend
    class LLM,Ollama ai
    class Store,SQLite storage
    class PDF export
    style API fill:#FDF4FF,stroke:#E879F9,color:#000000
```

## Detailed Diagram

```mermaid
flowchart LR
    UI["Streamlit frontend"]
    Docs["Swagger UI and OpenAPI<br/>GET /docs · GET /openapi.json"]

    subgraph API["FastAPI backend"]
        App["Application entry point<br/>main.py"]
        Reports["Report router<br/>api/reports.py"]
        Schemas["Pydantic validation<br/>schemas/reports.py"]

        subgraph Routes["API endpoints"]
            Health["GET /health"]
            Manual["POST /reports/manual"]
            Generate["POST /reports/generate"]
            Read["GET /reports<br/>GET /reports/{report_id}"]
            Edit["PATCH /reports/{report_id}"]
            Regenerate["POST /reports/{report_id}/regenerate"]
            Review["POST /reports/{report_id}/approve<br/>POST /reports/{report_id}/reopen<br/>DELETE /reports/{report_id}?revision=…"]
            Download["GET /reports/{report_id}/download"]
        end

        subgraph Components["Backend components"]
            LLM["Ollama client<br/>llm/ollama.py"]
            Prompt["DAP generation prompt<br/>dap_generation.txt"]
            Store["Report storage and revision checks<br/>db/drafts.py · db/connection.py"]
            PDF["PDF renderer<br/>export/pdf.py"]
        end

        App --> Health
        App --> Reports
        Reports --> Schemas
        Reports --> Manual & Generate & Read & Edit & Regenerate & Review & Download

        Manual -->|"Save blank DAP sections"| Store
        Generate -->|"Generate DAP sections"| LLM
        Generate -->|"Save notes and generated draft"| Store
        Read -->|"List, filter, or retrieve reports"| Store
        Edit -->|"Save edits against the current revision"| Store
        Regenerate -->|"Generate replacement sections"| LLM
        Regenerate -->|"Update the same report and increment its revision"| Store
        Review -->|"Check status and revision before writing"| Store
        Download -->|"Load the current saved report"| Store
        Download -->|"Render a draft or approved PDF"| PDF

        Prompt --> LLM
        LLM -->|"Validate the returned DAP sections"| Schemas
    end

    Ollama["Local Ollama server"]
    DB[("SQLite<br/>data/dap.db by default")]
    Template["School DAP PDF template"]

    UI <-->|"HTTP requests and responses"| App
    App --> Docs
    LLM <-->|"POST /api/chat"| Ollama
    Store <--> DB
    Template -->|"Base form for the first page"| PDF

    classDef frontend fill:#DBEAFE,stroke:#2563EB,color:#1E3A8A
    classDef backend fill:#EDE9FE,stroke:#7C3AED,color:#4C1D95
    classDef ai fill:#CCFBF1,stroke:#0F766E,color:#134E4A
    classDef storage fill:#DCFCE7,stroke:#15803D,color:#14532D
    classDef export fill:#FEF3C7,stroke:#B45309,color:#78350F

    class UI frontend
    class App,Docs,Reports,Schemas,Health,Manual,Generate,Read,Edit,Regenerate,Review backend
    class LLM,Prompt,Ollama ai
    class Store,DB storage
    class Download,PDF,Template export
    style API fill:#FDF4FF,stroke:#E879F9,color:#000000
```

## Local Setup

Run all commands in this guide from the **repository root**, which contains
`requirements.txt` and `pyproject.toml`.

Use Python 3.12. If you already have a working `.venv` for this project,
skip the creation command and use the environment you have.

**Windows (PowerShell)**

Use the creation command that matches your setup:

- If `python --version` shows Python 3.12, run `python -m venv .venv`.
- If `py -3.12 --version` shows Python 3.12, run `py -3.12 -m venv .venv`.
- If you still need Python 3.12, install the Python Install Manager, open a
  new PowerShell window, and run `py install 3.12`. Then run
  `py -3.12 -m venv .venv`. [Python Install Manager guide](https://docs.python.org/3/using/windows.html#python-install-manager)

Activate the environment with `.\.venv\Scripts\Activate.ps1`. If that
script is missing or PowerShell blocks it, use `.\.venv\Scripts\python.exe`
in place of `python` in the commands below.

**macOS and Linux (bash or zsh)**

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

Install the dependencies using the virtual environment's Python:

```bash
python -m pip install -r requirements.txt
```

## Local Account Setup

Account setup, backend login, report ownership, and administrator-only review
are available on the authentication branch. All report endpoints require a
valid bearer session. Sign in through Streamlit, or use `/docs` and its
**Authorize** button to test the backend directly.

Install the project in editable mode to make the `dap-assistant` command
available in your active virtual environment:

```bash
python -m pip install -e .
```

For synthetic-data demonstrations, explicitly create the two demo accounts:

```bash
dap-assistant init-demo-users
```

| Username | Password | Role |
| --- | --- | --- |
| `admin` | `password1234` | Administrator |
| `user` | `password1234` | Regular user |

Passwords are stored as salted Argon2id hashes. Demo accounts are not created
automatically, and rerunning this command does not reset existing passwords
or change existing roles. Use these public credentials only with synthetic data.

To add another account, run:

```bash
dap-assistant create-user
```

The command prompts for a username, display name, password, and password
confirmation. Password entry is hidden. New accounts default to the `user`
role; use `dap-assistant create-user --role admin` to create an administrator.
You can also supply `--username` and `--display-name`. Passwords are entered
interactively rather than passed as command arguments and must contain
15–1,024 characters. The explicit demo setup uses its shorter public password.

Both commands use the same SQLite database as FastAPI: `data/dap.db` relative
to the working directory, or the location set by `DAP_DB_PATH`. Run setup and
the backend with the same working directory and database setting. Running
`dap-assistant` without a subcommand still starts the backend and frontend.

### Backend Login and Sessions

After creating an account and starting FastAPI, open `/docs` and execute
`POST /auth/login` with the account's credentials:

```json
{"username": "user", "password": "password1234"}
```

Copy the returned `access_token`, click **Authorize** in Swagger UI, and paste
the token into the bearer-token field. Execute `GET /auth/me` to see the
signed-in account. Execute `POST /auth/logout` to revoke that session; using
the same token afterward returns `401`. Signing out leaves other sessions
for the account active.

Sessions expire eight hours after login, including across backend restarts.
Using a session does not extend its lifetime. SQLite stores only token hashes;
keep the returned token private. The backend checks account activity and the
current role on authenticated requests.

Five unsuccessful attempts for the same normalized username within five
minutes cause further attempts to return `429` with a `Retry-After` header.
The counter persists across backend restarts and resets after a successful
login or when the five-minute window expires. Unknown usernames receive the
same credential error and attempt limit. This is a local-app safeguard, not
a replacement for deployment-level rate limiting on a public server.

### Report Ownership Storage

Saved reports and history summaries include `owner_id`, which identifies the
owning account. Storage functions can create reports for an account and scope
reads to an authenticated viewer: regular users see their own reports, while
administrators see all reports. Ownership filtering happens before search
pagination. The API supplies the signed-in identity when creating, listing,
retrieving, editing, regenerating, deleting, or downloading reports.

Existing reports retain `owner_id: null` during database upgrades. Scoped
regular-user queries cannot see them; administrator queries can. Startup and
login never assign them automatically. The internal `assign_report_owner`
maintenance function can explicitly assign an unowned report to an existing
account without changing its content or revision. It cannot transfer a report
that already has an owner. Ownership is not accepted in report request bodies.

### Report Permissions

| Action | Regular user | Administrator |
| --- | --- | --- |
| Create a report | Own account | Own account |
| Read history, open reports, or download PDFs | Own reports | All reports |
| Edit, regenerate, or delete an unapproved draft | Own reports | Own reports |
| Approve or reopen a report | Not allowed | Any report |
| Edit or delete an approved report | Not allowed | Not allowed |

An administrator must reopen an approved report before its owner can correct
or delete it. Approval records the authenticated administrator's display name,
account ID, and a UTC timestamp. A supplied legacy `approved_by` field is
ignored; it cannot impersonate another reviewer. Reopening clears the approval
details and preserves report ownership.

Missing or expired sessions return `401`. Regular users receive `404` for
another user's report, including its PDF, without exposing whether it exists.
Administrator-only actions return `403` for regular users. Administrators also
receive `403` if they attempt to edit or delete content owned by someone else.

## Start the Server

```shell
python -m uvicorn documentation_assistant.backend.main:app --app-dir src --host 127.0.0.1 --port 8000 --reload
```

The server listens locally on port 8000. The `--reload` option restarts the
development server after code changes.
Change `--port` if another application is using port 8000.

## Shut Down the Server

Press **Ctrl+C** in the terminal running Uvicorn and wait for the shell
prompt to return. Saved reports remain in SQLite and are available the next
time you start FastAPI.

## Available Endpoints

| Endpoint | Purpose |
| --- | --- |
| [GET /health](http://127.0.0.1:8000/health) | Confirms the backend is responding. |
| [GET /docs](http://127.0.0.1:8000/docs) | Interactive API documentation. |
| [GET /openapi.json](http://127.0.0.1:8000/openapi.json) | Machine-readable API schema. |
| `POST /auth/login` | Exchanges account credentials for an expiring bearer token. |
| `GET /auth/me` | Retrieves the authenticated account's public identity and role. |
| `POST /auth/logout` | Revokes the supplied session token. |
| `POST /reports/generate` | Generates and saves an unapproved DAP draft from synthetic notes. |
| `POST /reports/manual` | Opens a draft with blank DAP sections and optional source notes. |
| `GET /reports` | Lists and filters saved report summaries, newest saved first. |
| `GET /reports/{report_id}` | Retrieves a saved report, its source notes, and its review state. |
| `GET /reports/{report_id}/download` | Downloads the current saved draft or approved report as a PDF. |
| `PATCH /reports/{report_id}` | Saves corrected source notes, DAP sections, or report details on a draft. |
| `POST /reports/{report_id}/regenerate` | Saves corrected notes and new AI-generated DAP sections on the same draft. |
| `DELETE /reports/{report_id}?revision=1` | Permanently deletes a draft if the supplied revision is current. |
| `POST /reports/{report_id}/approve` | Administrator only: approves the saved revision and makes it read-only. |
| `POST /reports/{report_id}/reopen` | Administrator only: returns the approved revision to draft for owner corrections. |

The health endpoint returns:

```json
{"status": "ok"}
```

This checks API liveness and works independently of Ollama. Startup initializes
SQLite before accepting requests; `/health` does not test model availability
or perform a database read on each call.

## Start a Draft

For manual writing, send optional notes and metadata to
`POST /reports/manual`. Use `{}` to start an empty report. The response contains
the saved notes and blank DAP sections. You can save a draft while sections are still blank and
approve it after all three contain text. You can create and review manual
drafts with Ollama stopped.

For AI-assisted writing, use `POST /reports/generate`. The API records the
draft source based on the endpoint used.

Start Ollama and run `ollama pull qwen3:8b` if the model is missing. The backend
uses Ollama on `127.0.0.1:11434`. To use a different installed model, set
`OLLAMA_MODEL` before starting the backend. [Local Ollama setup guide](../../../docs/LOCAL-OLLAMA-SETUP.md)

The backend creates one async HTTP client at startup for generation and
regeneration. It reuses available connections and closes the client at shutdown.
Creating the client does not contact Ollama, so manual workflows still work
with Ollama stopped. The client keeps the 240-second request timeout and
bypasses environment proxy settings for local Ollama requests.

- PowerShell: `$env:OLLAMA_MODEL = "your-model-tag"`
- bash or zsh: `export OLLAMA_MODEL="your-model-tag"`

In `/docs`, open **POST /reports/generate**, select **Try it out**, and submit:

Sign in and use **Authorize** first, as described under Backend Login and Sessions.

```json
{"notes": "Synthetic student practiced a breathing exercise and reported feeling calmer afterward."}
```

AI-assisted generation and regeneration require 1–4,000 characters of notes
after trimming surrounding whitespace. Manual draft notes are optional and
have the same maximum.

The response has a `report_id`, a `draft` status, and `data`, `assessment`, and
`plan` under `sections`. Use the ID in **GET /reports/{report_id}** to retrieve
the draft alongside its source notes, including after restarting the backend.
Retrieval works with Ollama stopped.

The API validates that all three generated sections contain text. The prompt
asks Ollama to use `Not documented.` when the source notes lack information for
a section. Review the draft against the original notes for accuracy and
completeness before approving it. Restart FastAPI after editing the prompt so
it loads the new instructions. [DAP prompt guide](llm/prompts/README.md)

SQLite creates `data/dap.db` during backend startup when launched from the
repository root. Startup also adds missing columns to older databases;
ordinary report requests do not repeat schema checks. To use another location,
set `DAP_DB_PATH` before starting the backend.

Use `GET /reports` to find a saved draft without already knowing its ID. Each
summary contains `report_id`, `status`, and a UTC `created_at` timestamp.
Drafts saved before timestamps were introduced have `created_at: null`.
The endpoint returns up to 25 reports by default, newest first. Use `limit`
(1–100) and `offset` (zero or greater) to request another page, such as
`GET /reports?limit=25&offset=25` for page two. Filters apply before pagination;
the response remains a JSON array and returns `[]` beyond the matching results.
When generating a draft, you can include a `metadata` object with
`student_name`, `student_id`, `school`, `grade`, `date_of_service`, and
`social_worker_name`.
Use a string for grade and `YYYY-MM-DD` for dates.

Send `metadata.start_time` and `metadata.end_time` as local 24-hour times in
`HH:MM` format. If the end precedes the start, the API returns `422`. This
also applies to a partial edit or regeneration request that changes one time
and conflicts with the other saved time. The response calculates
`metadata.total_minutes` when both times form a valid range.

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
that revision with any changes to `notes`, `sections`, or `metadata` to
`PATCH /reports/{report_id}`. Omit `sections` to keep the saved DAP text.
Include all three DAP fields when replacing `sections`. Within `metadata`,
include only the fields to change. Use `null` to clear an optional detail.
The response contains the new revision and the source notes. The report stays
in draft status. When review is complete, an administrator sends the reviewed
revision to `POST /reports/{report_id}/approve`. Replace the
example revision with the current revision returned by the API.

```json
{"revision": 2}
```

Approval records the signed-in administrator's name and a UTC `approved_at` timestamp and
makes the report read-only. Approval returns `409` if any DAP section is
blank. Editing or approving an already approved report also returns `409`.
If the revision is stale, reload the report and review the current version
before retrying. Editing and approval work with Ollama stopped.

## Regenerate From Corrected Notes

Call `POST /reports/{report_id}/regenerate` with the current draft revision
and the corrected notes. Include optional metadata changes in the same request.

```json
{"revision": 2, "notes": "The student practiced paced breathing."}
```

A successful response returns the full draft with the same report ID, the
corrected notes, replacement DAP sections, and an incremented revision.
Ollama errors leave the saved draft intact. Keep the user's corrected notes
in the form so they can retry. A stale revision or an approved report returns
`409`. Reload the report before retrying a stale edit.

## Reopen an Approved Report

After confirmation, an administrator calls `POST /reports/{report_id}/reopen` with the revision
shown on screen, such as `{"revision": 3}`. The response keeps the same report
ID and saved content, increases the revision, and sets the status to `draft`.
The approver name and approval timestamp are cleared. Review and approve the
report again after editing it. Reopening works with Ollama stopped.

An unknown report returns `404`. A report already in draft or a stale
revision returns `409`.

## Delete a Draft

After the user confirms deletion, call `DELETE /reports/{report_id}?revision=1`
with the revision shown on screen. A successful deletion permanently removes
the report and returns `204` with an empty body. An approved report or a stale
revision returns `409`. A missing report returns `404`. Deletion works with
Ollama stopped.

## Download a PDF

In `/docs`, open **GET /reports/{report_id}/download**, select **Try it out**,
and submit the UUID of a saved report. A successful response contains PDF
bytes with `Content-Type: application/pdf` and a filename in
`Content-Disposition`.

Drafts have a `-draft.pdf` filename suffix and **DRAFT** on every page.
Approved PDFs show the saved reviewer name and date. The export uses the
current saved report, so save any pending edits before downloading.
A missing report returns `404`. Downloading works with Ollama stopped.

## Tests

Run the backend unit and integration tests from the repository root. These
tests use mocked Ollama responses and temporary databases, so they do not
require a running FastAPI server or Ollama and do not change saved reports.

```shell
python -m pytest tests/unit -k "not frontend" -v
python -m pytest tests/integration -k "not frontend" -v
```

| Test group | Coverage |
| --- | --- |
| Unit: schemas | Notes and DAP validation, local 24-hour session times, partial time updates, and duration calculations. |
| Unit: authentication | Password hashing and verification, account validation, command dispatch, and login decisions. |
| Unit: storage and connections | Saving and mapping reports, missing records, connection setup, and transaction cleanup. |
| Unit: API handlers and Ollama client | Health responses, AI response validation and failures, and HTTP error mapping when saving regenerated reports. |
| Unit: PDF renderer | Field rendering, draft and approval markings, and continuation pages. |
| Integration: report API | Creation, filtering, editing, approval, reopening, deletion, missing reports, and stale revisions using real SQLite storage. |
| Integration: pagination and startup | Bounded filtered pages, pagination validation, and schema checks occurring only during startup. |
| Integration: AI generation | Mocked generation and regeneration through FastAPI, including edits or deletion while generation is in progress. |
| Integration: HTTP client lifecycle | Reuse across generation and regeneration, recovery after a connection failure, and cleanup at shutdown. |
| Integration: database compatibility | Upgrading an older table with missing columns while preserving saved notes and assigning defaults for new fields. |
| Integration: accounts and sessions | Account provisioning, credential checks, token storage, logout, expiry, restart persistence, disabled accounts, and login throttling. |
| Integration: ownership storage | Scoped reads, filtering before pagination, preserved ownership through review actions, legacy upgrades, explicit assignment, and account foreign keys. |
| Integration: report permissions | Real user sessions, cross-user isolation, owner-only writes, admin review, authenticated reviewer identity, revoked sessions, and ownership changes during regeneration. |
| Integration: PDF and health | PDF downloads from saved reports and health endpoint behavior. |

The database unit tests cover the existing-column path; the compatibility
integration test exercises the missing-column upgrade against real SQLite.

To run the backend and frontend suites together:

```shell
python -m pytest tests/unit tests/integration -v
```

To test actual model output, start Ollama and make sure the configured model
is installed. The live tests are skipped by default. Set
`RUN_LIVE_OLLAMA=1` to enable them. The `-s` flag shows the generated DAP text
for review.

**Windows (PowerShell)**

```powershell
$env:RUN_LIVE_OLLAMA = "1"
python -m pytest tests/llm -v -s
Remove-Item Env:RUN_LIVE_OLLAMA
```

**macOS and Linux (bash or zsh)**

```bash
RUN_LIVE_OLLAMA=1 python -m pytest tests/llm -v -s
```
