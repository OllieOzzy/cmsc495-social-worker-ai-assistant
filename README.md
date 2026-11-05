# cmsc495-social-worker-ai-assistant
AI-powered documentation assistant for school social workers, developed as a UMGC CMSC 495 capstone project.

## 🗂️ Proposed Repository Structure

```text
📁 cmsc495-social-worker-ai-assistant/
├── 📄 README.md
├── ⚙️ pyproject.toml
├── 📄 requirements.txt
├── ⚙️ .env.example
├── ⚙️ .gitignore
├── 📁 .github/
│   └── 📁 workflows/
│       └── ⚙️ ci.yml
├── 📁 docs/
│   ├── 📄 architecture.md
│   ├── 📄 api-contracts.md
│   ├── 📄 data-model.md
│   ├── 📄 local-llm-setup.md
│   ├── 📄 safety-and-limitations.md
│   ├── 📄 user-guide.md
│   └── 📁 templates/
│       └── 📋 School_Social_Work_DAP_Session_Note.pdf
├── 📁 src/
│   └── 📁 documentation_assistant/
│       ├── 🐍 __init__.py
│       ├── 📁 backend/
│       │   ├── 🐍 __init__.py
│       │   ├── 🐍 main.py
│       │   ├── 🐍 config.py
│       │   ├── 📁 api/
│       │   │   ├── 🐍 __init__.py
│       │   │   ├── 🐍 health.py
│       │   │   ├── 🐍 sessions.py
│       │   │   └── 🐍 reports.py
│       │   ├── 📁 schemas/
│       │   │   ├── 🐍 __init__.py
│       │   │   ├── 🐍 sessions.py
│       │   │   ├── 🐍 reports.py
│       │   │   └── 🐍 generation.py
│       │   ├── 📁 db/
│       │   │   ├── 🐍 __init__.py
│       │   │   ├── 🐍 connection.py
│       │   │   ├── 🐍 models.py
│       │   │   └── 🐍 repositories.py
│       │   ├── 📁 services/
│       │   │   ├── 🐍 __init__.py
│       │   │   ├── 🐍 generation.py
│       │   │   ├── 🐍 review.py
│       │   │   └── 🐍 pdf_export.py
│       │   └── 📁 llm/
│       │       ├── 🐍 __init__.py
│       │       ├── 🐍 base.py
│       │       ├── 🐍 mock.py
│       │       ├── 🐍 ollama.py
│       │       └── 📁 prompts/
│       │           └── 📝 dap_generation.txt
│       └── 📁 frontend/
│           ├── 🐍 __init__.py
│           ├── 🐍 app.py
│           ├── 🐍 config.py
│           ├── 🐍 api_client.py
│           └── 📁 components/
│               ├── 🐍 __init__.py
│               ├── 🐍 session_form.py
│               ├── 🐍 dap_editor.py
│               ├── 🐍 manual_fields.py
│               └── 🐍 session_history.py
├── 📁 tests/
│   ├── 🐍 conftest.py
│   ├── 📁 unit/
│   │   ├── 🧪 test_ci_demo.py
│   │   ├── 🧪 test_generation_validation.py
│   │   ├── 🧪 test_review_rules.py
│   │   └── 🧪 test_pdf_export.py
│   ├── 📁 integration/
│   │   ├── 🧪 test_ci_demo_cli.py
│   │   ├── 🧪 test_sessions_api.py
│   │   ├── 🧪 test_reports_api.py
│   │   └── 🧪 test_documentation_workflow.py
│   └── 📁 fixtures/
│       └── 📄 synthetic_sessions.json
├── 📁 scripts/
│   ├── 🐍 ci_demo.py
│   ├── 🐍 seed_demo.py
│   └── 🐍 smoke_test_ollama.py
└── 📁 data/
    └── 📄 .gitkeep
```

## Continuous Integration

GitHub Actions runs four jobs using Python 3.12 on pushes, pull requests, and
manual workflow runs:

| Job | Purpose |
| --- | --- |
| Linting | Ruff checks common Python mistakes and import ordering. |
| Formatting | Ruff checks consistent code formatting without changing files. |
| Unit tests | Pytest checks the demo function with missing and supplied synthetic notes. |
| Integration tests | Pytest runs the demo in a separate process and verifies argument parsing, JSON output, and errors. |

Jobs run in order: **Linting → Formatting → Unit tests → Integration tests**.
Each job starts only after the preceding job succeeds.
Each job has its own runner and installs dependencies from `requirements.txt`.
Failures block dependent jobs; missing tests are treated as failures.

The demo copies notes into Data and leaves Assessment and Plan as
`Not documented.` It is a deterministic CI example, not an LLM or the application
report generator. FastAPI, SQLite, and mock-provider integration tests will be
added during implementation. No GPU, Ollama server, secrets, or real student
records are needed for CI. Model inference remains local.

Run the checks locally from an activated Python 3.12 virtual environment:

```shell
python -m pip install -r requirements.txt
python -m ruff check .
python -m ruff format --check .
python -m pytest tests/unit -v
python -m pytest tests/integration -v
python scripts/ci_demo.py --notes "Synthetic student attended a session."
```

Use `python -m ruff format .` to apply formatting locally.
After pushing the workflow, open **Actions > CI** to inspect each job's logs.
A successful run validates this demo, not the future application's functionality.
