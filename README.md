# cmsc495-social-worker-ai-assistant
AI-powered documentation assistant for school social workers, developed as a UMGC CMSC 495 capstone project.

## 🗂️ Proposed Repository Structure

```text
📁 cmsc495-social-worker-ai-assistant/
├── 📄 README.md
├── ⚙️ pyproject.toml
├── ⚙️ .env.example
├── ⚙️ .gitignore
├── 📁 .github/
│   └── 📁 workflows/
│       └── ⚙️ ci.yml
├── 📁 docs/
│   ├── 📄 architecture.md
│   ├── 📄 api-contracts.md
│   ├── 📄 data-model.md
│   ├── 📄 safety-and-limitations.md
│   ├── 📄 user-guide.md
│   └── 📁 templates/
│       └── 📋 school_social_work_dap.pdf
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
│   │   ├── 🧪 test_generation_validation.py
│   │   ├── 🧪 test_review_rules.py
│   │   └── 🧪 test_pdf_export.py
│   ├── 📁 integration/
│   │   ├── 🧪 test_sessions_api.py
│   │   ├── 🧪 test_reports_api.py
│   │   └── 🧪 test_documentation_workflow.py
│   └── 📁 fixtures/
│       └── 📄 synthetic_sessions.json
├── 📁 scripts/
│   ├── 🐍 seed_demo.py
│   └── 🐍 smoke_test_ollama.py
└── 📁 data/
    └── 📄 .gitkeep
```
