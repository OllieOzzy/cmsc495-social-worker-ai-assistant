# Local LLM Setup and Smoke Tests

Use this guide to start Ollama and run standalone model checks with synthetic
notes. For the app's actual report generation, see [Test through FastAPI](#test-through-fastapi).
Review generated drafts against the source notes.

## Requirements

- Ollama installed and running.
- A compatible GPU or sufficient system memory for CPU inference.
- Internet access for the initial model download.
- Synthetic notes only.

The initial reference setup uses Windows, an NVIDIA RTX 3090, and Qwen3 8B.
Other hardware may require a smaller model.

Ollama and its model are not included in the app wheel. The handwritten
workflow works without them. For installing and launching the packaged app,
use the [main quick start](../README.md#quick-start).

## 1. Install and Verify Ollama

### Windows (PowerShell)

Install Ollama and open it from the Start menu. If a command times out,
quit Ollama from the system tray if it is running, reopen it from the Start
menu, and run `ollama list` to check that the server responds.
[Ollama Windows setup](https://docs.ollama.com/windows)

### macOS (Terminal)

Open the Ollama disk image, move Ollama to **Applications**, and launch it.
Follow the app's prompt to make the `ollama` command available in Terminal.
[Ollama macOS setup](https://docs.ollama.com/macos)

### Linux (Terminal)

Install Ollama with the official installer. [Ollama Linux setup](https://docs.ollama.com/linux)

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Run `ollama list` after installation. If it cannot reach Ollama, start the
installed systemd service with `sudo systemctl start ollama`. For a setup
without the service, run `ollama serve` and leave that terminal open. Run
the model commands in a second terminal.

### Verify on any platform

```shell
ollama --version
ollama list
```

The list can be empty before you download a model. On Windows or Linux with
an NVIDIA GPU, run `nvidia-smi` to check that the GPU and driver are detected.

## 2. Download and Start the Model

Download the model once:

```shell
ollama pull qwen3:8b
```

Start an interactive session:

```shell
ollama run qwen3:8b
```

Inside the Ollama chat, set a 4,096-token context for these standalone checks:

```text
/set parameter num_ctx 4096
```

At the Ollama chat prompt, enter three double quotes (`"""`) on their own line,
paste one complete sample prompt below, then enter three double quotes on a
new line to submit it as one message. [Ollama CLI multiline input](https://docs.ollama.com/cli#multiline-input)

For each test, start a fresh conversation. Enter `/bye`, run
`ollama run qwen3:8b` again, and set the context window again.

## 3. Test: Documented Intervention and Response

Paste the complete prompt:

```text
Create an unapproved school social work DAP draft using only the
synthetic notes below.

Return three sections:
Data: documented student statements, observations, and interventions.
Assessment: explicitly documented assessment or intervention response.
Plan: explicitly documented next steps.

Use "Not documented." when information is absent.
Do not invent diagnoses, observations, interventions, or follow-up plans.
Preserve uncertainty and identify student statements as reported information.
Do not complete risk reporting, signatures, credentials, or approval fields.

Notes:
Student S-001 reported feeling nervous before a presentation.
The social worker practiced a breathing exercise with the student.
The student said they felt calmer afterward.
```

### Review checklist

- [ ] Data includes the reported nervousness and breathing exercise.
- [ ] The draft identifies feeling calmer as the student's report.
- [ ] The draft does not diagnose anxiety or claim a clinical finding.
- [ ] Plan says "Not documented."
- [ ] No appointment, referral, or additional intervention is invented.
- [ ] The draft does not claim approval or add a signature.

Exact wording may vary. Evaluate whether every claim is supported by the notes.

## 4. Test: Sparse Notes

Start a fresh conversation and paste:

```text
Create an unapproved school social work DAP draft using only the
synthetic notes below.

Return Data, Assessment, and Plan.
Use "Not documented." when information is absent.
Do not infer mood, participation, progress, diagnoses, or future actions.
Do not complete risk reporting, signatures, credentials, or approval fields.

Notes:
Student S-002 attended a session.
```

### Review checklist

- [ ] Data records attendance without adding details.
- [ ] Assessment says "Not documented."
- [ ] Plan says "Not documented."
- [ ] No mood, behavior, intervention, or progress is invented.

## 5. Test: Uncertain Follow-Up

Start a fresh conversation and paste:

```text
Create an unapproved school social work DAP draft using only the
synthetic notes below.

Return Data, Assessment, and Plan.
Use "Not documented." when information is absent.
Preserve uncertainty. Do not turn a suggestion into a confirmed plan.
Do not invent diagnoses, dates, appointments, or completed actions.
Do not complete risk reporting, signatures, credentials, or approval fields.

Notes:
Student S-003 said they might be willing to attend another session.
No follow-up appointment was scheduled.
```

### Review checklist

- [ ] The student's willingness remains uncertain.
- [ ] Assessment says "Not documented."
- [ ] Plan states that no follow-up appointment was scheduled.
- [ ] No appointment date or commitment is invented.

## 6. Verify GPU Use

While the model is loaded, open a separate terminal:

```shell
ollama ps
```

Inspect the `PROCESSOR` column:

- `100% GPU`: the model is loaded on the GPU.
- A CPU/GPU split: part of the model runs on the CPU and uses system memory.
- CPU-only execution: investigate GPU compatibility, drivers, and available memory.

For NVIDIA GPU memory usage on Windows or Linux:

```shell
nvidia-smi
```

GPU use verifies execution placement, not report accuracy.

## 7. Verify the Local API

In PowerShell:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags"
```

On macOS or Linux:

```bash
curl -fsS http://127.0.0.1:11434/api/tags
```

The response should list the downloaded model.

This checks the Ollama API that the FastAPI backend connects to.

## 8. Record Results

Record the following for each test session:

| Item | Result |
| --- | --- |
| Date and tester | |
| Operating system | |
| GPU and VRAM | |
| Ollama version | |
| Model tag and ID from `ollama list` | |
| Context window | 4096 |
| GPU/CPU placement | |
| Approximate response time | |
| Test 1 result | Pass / Fail |
| Test 2 result | Pass / Fail |
| Test 3 result | Pass / Fail |
| Unsupported details observed | |
| Other observations | |

Save the exact synthetic prompt and response for any failure.
Repeat cases to check consistency; one successful response is not sufficient
evidence of reliable grounding.

## 9. Stop the Session

Exit the interactive chat:

```text
/bye
```

Unload the model from memory:

```shell
ollama stop qwen3:8b
```

The downloaded model remains available and the Ollama server keeps running.
To shut down the server, quit the desktop app on Windows or macOS, press
**Ctrl+C** in the terminal running `ollama serve`, or run
`sudo systemctl stop ollama` if Linux is running it as a systemd service.

## Test through FastAPI

The backend sends the [DAP prompt](../src/documentation_assistant/backend/llm/prompts/dap_generation.txt) with each
request, sets an 8,192-token context, and validates the structured JSON
response. An interactive `/set` command applies to the standalone chat.

The app defaults to `qwen3:8b`, uses temperature `0`, limits generated output
to 1,200 tokens, and uses a 240-second HTTP request timeout. A timeout is an
error limit, not an expected generation time. The frontend allows an additional
15 seconds for the backend response.

To use another compatible installed model, set `OLLAMA_MODEL` in the terminal
that starts the backend or `dap-assistant`. Use its exact tag from `ollama list`:

```powershell
# Windows PowerShell, before launching the app
$env:OLLAMA_MODEL = "your-installed-model-tag"
```

```bash
# macOS or Linux, before launching the app
export OLLAMA_MODEL="your-installed-model-tag"
```

Then start the app using the quick-start commands, or start FastAPI using
the backend guide. No wheel rebuild is needed. Changing the model still
requires checking its structured output and reviewing draft quality. The
GitHub live workflow uses `qwen3:4b` for its runner tests; that does not change
the app's local default.

In 2.0.0, report endpoints require an authenticated account. Create initial
accounts against the backend's database, then start FastAPI and open `/docs`.
Execute `POST /auth/login`, copy the returned `access_token`, and paste it into
Swagger's **Authorize** bearer-token field. Send synthetic notes to
`POST /reports/generate`; the draft belongs to the signed-in user. See the
[account setup guide](../src/documentation_assistant/backend/README.md#local-account-setup).

To run automated live
tests, keep Ollama running with the configured model installed and follow
the [backend test instructions](../src/documentation_assistant/backend/README.md#tests).

## References

- [Ollama Windows setup](https://docs.ollama.com/windows)
- [Qwen3 8B model](https://ollama.com/library/qwen3:8b)
- [Context length and GPU offloading](https://docs.ollama.com/context-length)
