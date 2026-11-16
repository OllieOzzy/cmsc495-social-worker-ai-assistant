# DAP Documentation Assistant

AI-powered documentation assistant for school social workers, developed as a UMGC CMSC 495 capstone project.

See the [local Ollama setup guide](docs/local-llm-setup.md) for installation and model checks on Windows, macOS, and Linux.

## 🗂️ Repository Structure

```text
📁 cmsc495-social-worker-ai-assistant/
├── 📄 README.md
├── ⚙️ pyproject.toml
├── 📄 requirements.txt
├── ⚙️ .gitattributes
├── ⚙️ .gitignore
├── 📁 .github/
│   ├── 📁 actions/
│   │   └── 📁 setup-live-ollama/
│   │       └── ⚙️ action.yml
│   └── 📁 workflows/
│       ├── ⚙️ ci.yml
│       └── ⚙️ live-ollama.yml
├── 📁 docs/
│   ├── 📄 local-llm-setup.md
│   └── 📁 templates/
│       └── 📋 School_Social_Work_DAP_Session_Note.pdf
├── 📁 scripts/
│   └── 🐍 preview_pdf.py
├── 📁 src/
│   └── 📁 documentation_assistant/
│       ├── 🐍 __init__.py
│       ├── 📁 backend/
│       │   ├── 📄 README.md
│       │   ├── 🐍 __init__.py
│       │   ├── 🐍 main.py
│       │   ├── 📁 api/
│       │   │   ├── 🐍 __init__.py
│       │   │   ├── 🐍 health.py
│       │   │   └── 🐍 reports.py
│       │   ├── 📁 db/
│       │   │   ├── 🐍 __init__.py
│       │   │   ├── 🐍 connection.py
│       │   │   └── 🐍 drafts.py
│       │   ├── 📁 export/
│       │   │   ├── 🐍 __init__.py
│       │   │   ├── 🐍 pdf.py
│       │   │   └── 📁 templates/
│       │   │       └── 📋 School_Social_Work_DAP_Session_Note.pdf
│       │   ├── 📁 llm/
│       │   │   ├── 🐍 __init__.py
│       │   │   ├── 🐍 ollama.py
│       │   │   └── 📁 prompts/
│       │   │       ├── 📄 README.md
│       │   │       └── 📝 dap_generation.txt
│       │   └── 📁 schemas/
│       │       ├── 🐍 __init__.py
│       │       └── 🐍 reports.py
│       └── 📁 frontend/
│           ├── 📄 README.md
│           ├── 🐍 __init__.py
│           ├── 🐍 api_client.py
│           ├── 🐍 app.py
│           ├── 🐍 forms.py
│           ├── 🐍 reports.py
│           └── 🐍 sidebar.py
└── 📁 tests/
    ├── 📁 integration/
    │   ├── 🧪 test_health_api.py
    │   ├── 🧪 test_report_pdf.py
    │   └── 🧪 test_reports_api.py
    ├── 📁 llm/
    │   ├── 🧪 test_dap_quality.py
    │   └── 🧪 test_live_ollama.py
    └── 📁 unit/
        ├── 🧪 test_db_connection.py
        ├── 🧪 test_drafts.py
        ├── 🧪 test_health_handler.py
        ├── 🧪 test_ollama.py
        ├── 🧪 test_pdf_renderer.py
        ├── 🧪 test_report_handlers.py
        └── 🧪 test_report_schemas.py
```

The backend creates the local SQLite file at `data/dap.db` on first use when
started from the repository root. Git ignores the `data/` folder.

## Architecture

```mermaid
flowchart TD
    Worker["School social worker"]
    UI["Streamlit frontend"]
    API["FastAPI backend"]
    AI["Local Ollama"]
    DB[("Local SQLite")]
    PDF["PDF exporter"]

    Worker -->|"Enter notes or start a manual draft"| UI
    UI -->|"Show source notes and DAP for review"| Worker
    UI <-->|"Report requests, responses, and PDFs"| API
    API <-->|"Generate DAP from source notes"| AI
    API <-->|"Store and retrieve notes and reports"| DB
    API <-->|"Export a saved draft or approved report"| PDF

    classDef user fill:#F1F5F9,stroke:#64748B,color:#0F172A,stroke-width:2px
    classDef frontend fill:#DBEAFE,stroke:#2563EB,color:#1E3A8A,stroke-width:2px
    classDef backend fill:#FDF4FF,stroke:#E879F9,color:#000000,stroke-width:2px
    classDef ai fill:#CCFBF1,stroke:#0F766E,color:#134E4A,stroke-width:2px
    classDef storage fill:#DCFCE7,stroke:#15803D,color:#14532D,stroke-width:2px
    classDef export fill:#FEF3C7,stroke:#B45309,color:#78350F,stroke-width:2px

    class Worker user
    class UI frontend
    class API backend
    class AI ai
    class DB storage
    class PDF export
```

See the [frontend guide](src/documentation_assistant/frontend/README.md) and
[backend guide](src/documentation_assistant/backend/README.md) for setup and
detailed diagrams.

## Continuous Integration

```mermaid
flowchart TD
    Start["Push, pull request, or manual run"]
    Start --> Checks["Workflow and Python linting, formatting, and security checks"]
    Start --> Unit["Unit tests"]
    Start --> Integration["Integration tests"]

    Unit --> Coverage["Coverage report · 90% minimum"]
    Integration --> Coverage
    Checks --> Build["Build one wheel after all checks pass"]
    Coverage --> Build

    Build --> Windows["Validate on Windows"]
    Build --> Linux["Validate on Ubuntu"]
    Build --> Mac["Validate on macOS"]

    Windows --> Gate{"All three passed and eligible for upload?"}
    Linux --> Gate
    Mac --> Gate
    Gate -->|"PR targeting main or manual run on main"| Upload["Upload dap-app-1.0.0.zip"]
    Gate -->|"Other CI runs"| Skip["Skip final upload"]

    classDef trigger fill:#F1F5F9,stroke:#64748B,color:#0F172A,stroke-width:2px
    classDef checks fill:#DBEAFE,stroke:#2563EB,color:#1E3A8A,stroke-width:2px
    classDef build fill:#EDE9FE,stroke:#7C3AED,color:#4C1D95,stroke-width:2px
    classDef validation fill:#CCFBF1,stroke:#0F766E,color:#134E4A,stroke-width:2px
    classDef decision fill:#FEF3C7,stroke:#B45309,color:#78350F,stroke-width:2px
    classDef artifact fill:#DCFCE7,stroke:#15803D,color:#14532D,stroke-width:2px

    class Start,Skip trigger
    class Checks,Unit,Integration,Coverage checks
    class Build build
    class Windows,Linux,Mac validation
    class Gate decision
    class Upload artifact
```

The [CI Pipeline](.github/workflows/ci.yml) runs on pushes, pull requests, and
manual runs. It uses Ubuntu 24.04 and Python 3.12 for the Python checks.

| Job | What it checks |
| --- | --- |
| Workflow Linting | actionlint checks GitHub Actions workflow syntax and expressions. |
| Workflow Formatting | Prettier checks YAML formatting under `.github/`. |
| Workflow Security | zizmor reports security findings. Scanner errors fail the job. |
| Python Linting | Ruff checks for issues such as unused imports. |
| Python Formatting | Ruff checks Python formatting. |
| Python Security | Bandit scans the backend Python code. |
| Dependency Security | pip-audit checks the dependencies in `requirements.txt` for known vulnerabilities. |
| Unit Tests | Pytest checks individual pieces, including report validation and Ollama response parsing. |
| Integration Tests | Pytest checks workflows such as saving reports in SQLite and downloading PDFs through FastAPI. |
| Coverage Report | Combines unit and integration coverage, publishes the report in the run summary, and fails below 90% backend coverage. |
| Build Wheel | Builds one wheel for the validation jobs. |
| Validate Wheel | Installs the wheel on Ubuntu, Windows, and macOS with Python 3.12 and checks that the installed app can save a draft and export a PDF. |
| Upload Validated Wheel | Adds the versioned ZIP to successful pull request runs targeting `main` and manual runs on `main`. |

Linting, formatting, security checks, unit tests, and integration tests run in
parallel. Coverage waits for both test jobs. The wheel build waits for coverage
and all other checks to pass. The regular pipeline uses synthetic data and mocks
Ollama responses where needed, so it runs without Ollama or a GPU. View the
results under **Actions → CI Pipeline**.

To prepare a release, run **CI Pipeline** manually on `main`. After the wheel
checks pass, download `dap-app-<version>` from **Artifacts** and extract the
`.whl` for the GitHub Release.

### Live Ollama CI Pipeline

```mermaid
flowchart TD
    Start["Manually run Live Ollama Test"]
    Start --> Ubuntu["Ubuntu smoke test"]
    Start --> Windows["Windows smoke test"]
    Start --> Mac["macOS smoke test"]
    Start -->|"If quality tests are selected"| Quality["Ubuntu DAP quality tests"]

    classDef trigger fill:#F1F5F9,stroke:#64748B,color:#0F172A,stroke-width:2px
    classDef smoke fill:#CCFBF1,stroke:#0F766E,color:#134E4A,stroke-width:2px
    classDef quality fill:#FEF3C7,stroke:#B45309,color:#78350F,stroke-width:2px

    class Start trigger
    class Ubuntu,Windows,Mac smoke
    class Quality quality
```

To check actual model output, go to **Actions → Live Ollama Test → Run workflow**.
The [live workflow](.github/workflows/live-ollama.yml) runs Ollama with
`qwen3:4b` on Ubuntu, Windows, and macOS. Each smoke test verifies that the
backend can generate and save a draft. Select **Run the Ubuntu DAP quality cases
alongside the smoke tests** to check generated sections against synthetic notes
and print the drafts for review. The quality job runs independently on Ubuntu.

### Run Python checks locally

From the repository root, use your Python 3.12 virtual environment:

```shell
python -m pip install -r requirements.txt
python -m ruff check .
python -m ruff format --check .
python -m pytest tests/unit -v
python -m pytest tests/integration -v
```

For live model tests on your own machine, follow the
[backend test instructions](src/documentation_assistant/backend/README.md#tests).

## Upcoming release 1.1.0

- **Document scanning with OCR.** Extract text from scanned documents and review
  it before using it as session notes in the app.
- **Docker Compose setup.** Run the Streamlit frontend, FastAPI backend, and
  Ollama as separate containers on one machine.
