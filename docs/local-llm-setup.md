# Local LLM Setup and Smoke Tests

This guide verifies that Ollama can run a local model and produce preliminary
DAP documentation drafts from synthetic notes.

These manual checks do not prove the model is safe or accurate for real
student records. All generated reports require human review.

## Requirements

- Ollama installed and running.
- A compatible GPU or sufficient system memory for CPU inference.
- Internet access for the initial model download.
- Synthetic notes only.

The initial reference setup uses Windows, an NVIDIA RTX 3090, and Qwen3 8B.
Other hardware may require a smaller model.

## 1. Verify Installation

Open PowerShell:

```powershell
ollama --version
```

For NVIDIA systems, verify the GPU and driver are detected:

```powershell
nvidia-smi
```

## 2. Download and Start the Model

Download the model once:

```powershell
ollama pull qwen3:8b
```

Start an interactive session:

```powershell
ollama run qwen3:8b
```

Inside the Ollama chat, set the context window:

```text
/set parameter num_ctx 4096
```

The following prompts are entered into the Ollama chat, not directly into
PowerShell.

For each test, use a fresh conversation. Type `/bye`, restart the model,
and set the context window again.

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

While the model is loaded, open a separate PowerShell window:

```powershell
ollama ps
```

Inspect the `PROCESSOR` column:

- `100% GPU`: the model is loaded on the GPU.
- A CPU/GPU split: some processing is offloaded to system memory.
- CPU-only execution: investigate GPU compatibility, drivers, and available memory.

For NVIDIA GPU memory usage:

```powershell
nvidia-smi
```

GPU use verifies execution placement, not report accuracy.

## 7. Verify the Local API

In PowerShell:

```powershell
Invoke-RestMethod -Uri "http://localhost:11434/api/tags"
```

The response should list the downloaded model.

This confirms that the local API is reachable. It does not test the future
FastAPI application.

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

```powershell
ollama stop qwen3:8b
```

The downloaded model remains available for later use.

## References

- [Ollama Windows setup](https://docs.ollama.com/windows)
- [Qwen3 8B model](https://ollama.com/library/qwen3:8b)
- [Context length and GPU offloading](https://docs.ollama.com/context-length)
```
