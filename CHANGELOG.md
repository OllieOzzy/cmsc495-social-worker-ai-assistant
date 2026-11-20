# Changelog

Major changes to the DAP Documentation Assistant. Versions use release tags
such as `1.0.0` and `1.1.0`, without a `v` prefix.

## 1.1.0

This release focuses on reliability, regression testing, and reducing repeated
work before adding features such as OCR or containerization.

### Added

- Frontend unit tests for API handling, forms, sidebar navigation, routing,
  report actions, and PDF download controls.
- Frontend integration tests for saving and reopening reports, approval and
  reopening, deletion, unsaved changes, stale saves, and backend reconnection.
- Backend regression tests for session-time validation, partial updates,
  missing reports, and edits or deletion during AI regeneration.
- Tests for HTTP client reuse, browser-session isolation, cleanup, and local
  access when environment proxies are configured.

### Changed

- Report history displays 25 reports per page with Previous and Next controls.
  Applying or clearing filters returns to the first page.
- `GET /reports` now returns up to 25 summaries by default. API clients can
  request pages with `limit` (1–100) and `offset` (zero or greater). The response
  remains a JSON array; filters apply before pagination.
- Service-status results are reused for 60 seconds across full-page reruns.
  Startup checks, automatic refreshes, and immediate manual retries remain.
- SQLite table creation and missing-column upgrades run during backend startup
  instead of on every storage operation.
- Generation and regeneration share an async Ollama HTTP client until backend
  shutdown. The 240-second timeout and proxy bypass remain unchanged.
- Frontend HTTP clients are reused within each browser session and proxy policy,
  then closed when Streamlit releases their cached resources.
- Wheel building, cross-platform validation, and artifact upload run only on
  pushes to `main` or manual workflow runs on `main`. Branch and PR runs retain
  the regular checks and tests.
- Setup, testing, release, and troubleshooting guides reflect the packaged app
  and the updated frontend and backend behavior.

### Fixed

- The generation prompt explicitly places a student's documented response to an
  intervention in Assessment, with regression checks for improvement, no reported
  improvement, and an intervention without a recorded response.
- Malformed JSON and missing or unusable API error details no longer break
  frontend error reporting; a fallback message is shown.
- HTTP `422` responses display actionable session-time and field-validation
  explanations without showing submitted input or internal error context.
- Local backend requests bypass environment proxies for localhost and literal
  loopback IPs. Remote backends retain environment proxy and certificate settings.
- Windows installed-wheel checks clean up the launcher process tree before
  removing temporary files and stream launcher output into CI logs.

### Upgrade Notes

- Stop the app and back up its database before upgrading. Install
  `dap_app-1.1.0-py3-none-any.whl` using the existing environment's Python, then
  launch from the same working folder or retain the same `DAP_DB_PATH`.
- Existing reports remain in SQLite. Startup adds missing columns when needed.
- API consumers that previously expected all reports from one request must
  follow pagination to retrieve the complete history.
- Python 3.12 remains the documented and CI-tested setup. Ollama and its model
  are separate installations; handwritten drafts do not require them.

## 1.0.0

Initial packaged release with:

- Manual and local AI-assisted DAP drafting with source-note review.
- SQLite report storage, search filters, and revision conflict checks.
- Editing, regeneration, approval, reopening, and draft deletion workflows.
- Template-based PDF exports with continuation pages and draft or approval markings.
- The `dap-assistant` launcher for FastAPI and Streamlit.
- A Python wheel, cross-platform installed-app CI checks, and live Ollama tests.
