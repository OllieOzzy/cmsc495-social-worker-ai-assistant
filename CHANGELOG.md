# Changelog

Major changes to the DAP Documentation Assistant.

## 2.0.0

This major release introduces authentication and account-based access.

### Breaking Changes and Upgrade

- Report endpoints now require a bearer session. Existing clients must sign in
  with `POST /auth/login` before accessing reports.
- Approval and reopening require an admin; draft editing and deletion require
  ownership. Administrators can review all reports but cannot edit another
  user's draft content.
- Back up the database with the app stopped, install the 2.0.0 wheel, and create
  the initial accounts against the same `DAP_DB_PATH` and working directory.
- Older reports remain unassigned and admin-visible. No automatic ownership
  assignment occurs; explicit assignment is a trusted maintenance operation.

### Added

- Authentication failure history in the existing administrator audit view:
  failed and throttled logins and current-password attempts, including unknown
  usernames, without credential values or report content. Authentication entries
  are limited to 30 days and 10,000 events while retaining account-change history.
- Transactional upgrade of earlier audit-table constraints, preserving existing
  records and event IDs while allowing unknown authentication targets.
- Read-only administrator account audit history in Manage users and
  `GET /users/audit-events`, with bounded newest-first pages and optional
  target-account filtering in the API.
- Transactional audit entries for account creation, renaming, role and
  activation changes, admin password resets, and self-service password changes.
  Entries retain stable actor/target IDs and username snapshots, UTC timestamps,
  and allowlisted public changes. No credential values or report content are logged.
- Automatic creation of the audit table in existing databases without
  reconstructing past events. CLI actions are recorded as local operations.

- Administrator account search by partial username or display name, with
  Unicode case-insensitive literal matching and backend pagination. Changing
  or clearing the query resets pagination and the selected account.

- Admin-only role changes in Manage users and `PATCH /users/{user_id}/role`.
  Actual changes revoke all sessions and require a new login. Atomic checks
  protect the last active admin across concurrent demotions and deactivations.
  Reports and approval history are preserved, and inactive accounts stay inactive.
- Login persistence rechecks the verified role to prevent an in-flight login
  from issuing a session after a concurrent role change.

- Local user accounts with regular-user and administrator roles, salted
  Argon2id password hashes, and terminal account-creation commands.
- Explicit demo setup for `admin` and `user`; existing credentials and roles
  are preserved when setup runs again.
- Backend login, account lookup, and logout with hashed session tokens,
  eight-hour expiry, and persisted login-attempt throttling.
- Report ownership, scoped history and PDF access, owner-only draft changes,
  and administrator-only approval and reopening.
- Streamlit sign-in and sign-out, role-based controls, session verification,
  and clearing of private state after logout, expiry, or a revoked session.
- Authentication and permission regression tests and authenticated
  installed-wheel validation.
- Administrator-only user management in Streamlit and FastAPI for listing
  accounts, creating users, and changing activation status. Deactivation
  revokes all sessions while preserving reports and approval records.
- Protection against self-deactivation and removal of the last active
  administrator, including concurrent status changes.
- Administrator password reset through Manage users and
  `POST /users/{user_id}/reset-password`, with matching password confirmation in
  the UI, session revocation, and preservation of account details and reports.
- A credential recheck when saving login sessions prevents an in-flight login
  from issuing a token after its password is reset or its account is deactivated.
- Self-service password change for signed-in users, requiring the current
  password and a confirmed replacement. Successful changes revoke all sessions.
- Password changes share the login attempt limit and recheck the verified hash
  under the write lock, preventing stale changes from overwriting an admin reset.
- Admin-only username and display-name editing in Manage users and
  `PATCH /users/{user_id}/profile`. Username changes revoke sessions while
  display-only edits keep them. IDs, reports, and past approver names are preserved.
- Username rechecks prevent in-flight logins and password changes from
  bypassing a concurrent username change.

### Changed

- CI collects backend and frontend coverage and publishes separate reports,
  each with a 90% minimum. Both reports are produced even if one threshold fails.
- CI's Python Security job scans both backend and frontend code with Bandit.
- Branch pushes build a candidate wheel after all regular checks pass and
  expose it as `app-wheel-candidate`. Cross-platform validation remains limited
  to PRs targeting `main`, pushes to `main`, and manual runs on `main`; the final
  versioned artifact is still uploaded only for main pushes and manual main runs.
- Session authentication resolves the token and current public account fields
  in one joined query and one connection, avoiding a second account lookup
  and unnecessary password-hash reads. Expiry and permission checks remain fresh.
- SQLite indexes support account-wide session revocation, expired-session
  cleanup, and expired login-attempt cleanup. Startup adds them to existing
  databases without changing account, session, or audit records.
- Account-filtered audit history uses a direct target predicate and the
  existing target/event index, avoiding a full-table scan and extra sorting.
- Report endpoints require a valid bearer token. Approval records the signed-in
  administrator's identity rather than a client-supplied reviewer name.
- Account and session tables are added to the existing report database.
  Older reports remain unassigned; authenticated regular users cannot see
  them, and administrators can review them. No automatic assignment occurs.
- Sensitive report JSON responses use `Cache-Control: no-store`, matching
  the existing PDF and authentication response protections.

### Fixed

- Idle frontend sessions verify server-side validity every 60 seconds and clear
  private state when a session is revoked. Failed checks force a full-page
  authentication gate, and recent full-page checks avoid duplicate requests.
- AI generation and regeneration revalidate the initiating session inside the
  report write transaction. Revoked, expired, or disabled sessions return `401`
  without inserting a draft or changing an existing report.

### Setup Notes

- Create accounts explicitly before signing in. Public demo credentials are
  for synthetic data only; ordinary account creation requires a password of
  15–1,024 characters.
- Account setup and the launcher must use the same database path. Approved
  reports remain protected from deletion, including by administrators.

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
- Wheel building and cross-platform validation run on PRs targeting `main`,
  pushes to `main`, and manual runs on `main`. Other branch runs retain the
  regular checks and tests. The final versioned artifact upload remains limited
  to pushes and manual runs on `main`.
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
