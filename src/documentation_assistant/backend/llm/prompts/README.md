# School Social Work DAP Note Prompt

A system prompt that turns unstructured school social work session notes into a **DAP (Data, Assessment, Plan)** JSON draft for review. Use synthetic student notes during development and testing.

## Overview

This prompt instructs an LLM to act as a strict clinical documentation formatter. Rather than inventing clinical interpretations or diagnoses, it extracts only explicitly documented facts, observations, and next steps from messy session notes and organizes them into a standardized JSON structure for clinician review.

## Key Features & Guardrails

* **Name handling in generated drafts.** The prompt asks the model to omit personal names from the three generated sections and use roles such as "the student" or "the teacher." The app stores the original source notes as entered.
* **Strict Anti-Hallucination Rules:** Prohibits adding diagnoses, motives, unstated interventions, or formal risk/mandated-reporting determinations.
* **Uncertainty & Denial Preservation:** Distinguishes secondhand reports from witnessed events, preserves client denials/disagreements, and avoids turning conditional statements (*"wants to try"*, *"might"*) into firm commitments.
* **Out-of-Order Parsing:** Reads the entire note—including late additions or timestamped jumps—and sequences events chronologically when clear.
* **Prompt Injection Defense:** Instructs the model to treat supplied notes strictly as source text and ignore any embedded commands.
* **Human-in-the-Loop Design:** Outputs an **unapproved draft** without signatures or credentials, leaving final clinical sign-off to the social worker.

## Output Schema

The backend validates that the model returns a JSON object with three nonblank text fields. The prompt asks the model to use `"Not documented."` when the notes contain no supported information for a section. The social worker reviews the draft against the original notes for accuracy and completeness.

```json
{
  "data": "What was reported, observed, or practiced during the session.",
  "assessment": "Documented progress, explicit clinical observations, or response to interventions.",
  "plan": "Explicitly documented next steps, timing, conditions, or pending decisions."
}
```

## Section Breakdown

| Section | What It Captures | What It Excludes |
| :--- | :--- | :--- |
| **Data** | Direct quotes, reported concerns, witnessed behaviors, and interventions practiced in session. | Future action items, unverified rumors stated as fact, and personal names. |
| **Assessment** | Student response to interventions, level of support/cueing needed, goal progress, and explicit clinician observations. | Activity descriptions already covered in Data, inferred diagnoses, or assumed improvement from completing a task. |
| **Plan** | Agreed next steps, conditional plans, actor/timing details, and explicit statements that no follow-up is planned. | Inferred future meetings, unstated referrals, or turning suggestions into commitments. |

## Few-Shot Examples Included

The prompt includes **5 targeted examples** to anchor model behavior on common documentation edge cases:
1. **Standard Session:** Basic anxiety report, coping skill practice, and `"Not documented."` Plan.
2. **Retrospective / Scaffolded Practice:** Out-of-order notes, cueing levels across attempts, and *"wants to try"* vs. *"agreed to"*.
3. **Activity Only:** Pure factual action with `"Not documented."` for both Assessment and Plan.
4. **Multi-Name & Secondhand Report:** Redacting teacher/student names, separating email reports from direct quotes, and attributing clinical patterns.
5. **Prompt Injection & Ambiguity:** Ignoring fake approval commands embedded in notes and omitting unclear/cut-off details.
