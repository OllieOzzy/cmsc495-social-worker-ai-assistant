"""Check live DAP drafts against synthetic notes and show them for review.

These opt-in tests need a running Ollama server and its configured model.
Keyword and placeholder checks catch selected regressions; the printed review
checklist still requires a person to assess meaning and unsupported claims.
"""

import os
import re

import pytest

from documentation_assistant.backend.main import create_app
from tests.auth_helpers import AuthenticatedTestClient as TestClient

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_OLLAMA") != "1",
    reason="Set RUN_LIVE_OLLAMA=1 to test against a running local Ollama server.",
)


@pytest.mark.parametrize(
    ("notes", "review", "required_words", "forbidden_words", "missing_sections"),
    [
        pytest.param(
            "The student reported feeling nervous before math. The social worker "
            "practiced paced breathing with the student. The student reported "
            "feeling calmer afterward.",
            "Data records the exercise. Assessment attributes feeling calmer to "
            "the student's report. Plan is Not documented.",
            {"data": "breathing", "assessment": "calmer"},
            (),
            ("plan",),
            id="no-follow-up",
        ),  # The response belongs in Assessment even when there is no Plan.
        pytest.param(
            "The social worker practiced a grounding exercise with the student. "
            "The student said they still felt nervous afterward.",
            "Assessment preserves the student's reported nervousness after the "
            "exercise without claiming improvement. Plan is Not documented.",
            {"data": "grounding", "assessment": "nervous"},
            ("calmer",),
            ("plan",),
            id="no-reported-improvement",
        ),  # A documented response can describe no improvement.
        pytest.param(
            "The social worker practiced paced breathing with the student. "
            "No student response was recorded.",
            "Data records the exercise. Assessment and Plan are Not documented; "
            "the exercise alone does not establish a response or progress.",
            {"data": "breathing"},
            (),
            ("assessment", "plan"),
            id="intervention-without-response",
        ),  # The Assessment rule must not turn an activity into an assumed outcome.
        pytest.param(
            "The student practiced asking the teacher for help. The student needed "
            "a cue on the first try and made the request independently on the "
            "second try. The social worker and student agreed to meet again on "
            "Friday after lunch.",
            "Assessment includes the first and second attempts. Plan keeps Friday "
            "after lunch and identifies who agreed to meet.",
            {"plan": "friday"},
            (),
            (),
            id="agreed-follow-up",
        ),  # Pytest checks the day. Review the time and who agreed to meet.
        pytest.param(
            "after the talk Alex was talking quieter, said he felt calmer. forgot "
            "to write above he was upset when he came in and was pacing by the "
            "door. he said he threw furnitures in the hallway earlier. we tried "
            "slow breathing two times, first he didnt join in then he tried it "
            "with me the second time.",
            "Use 'the student' and correct the grammar and spelling. Preserve the "
            "hallway report, the two breathing attempts, and how the student "
            "responded. Plan is Not documented.",
            {"data": "breathing", "assessment": "first"},
            ("alex", "furnitures"),
            ("plan",),
            id="messy-notes",
        ),  # Check that the name and typo are gone. Review what the rewrite kept.
        pytest.param(
            "The student heard peers laughing in the hallway and thought they "
            "might be laughing at them. The student said they did not hear what "
            "the peers said. The social worker did not witness the incident.",
            "Attribute the account to the student and preserve their uncertainty. "
            "Keep the fact that the social worker did not witness it. Check for "
            "any invented diagnosis or follow-up.",
            {},
            ("anxiety disorder", "panic attack"),
            ("plan",),
            id="uncertain-account",
        ),  # Review whether the draft preserves the student's uncertainty.
        pytest.param(
            "The social worker showed the student a printed copy of the school schedule.",
            "Data records what the social worker did. Assessment and Plan both say "
            "Not documented.",
            {"data": "schedule"},
            (),
            ("assessment", "plan"),
            id="no-assessment",
        ),  # The note gives no student response, progress, or next step.
    ],
)
def test_dap_prompt_with_live_ollama(
    monkeypatch,
    tmp_path,
    notes,
    review,
    required_words,
    forbidden_words,
    missing_sections,
):
    """Check the generated draft against the expectations for this case.

    Each entry in missing_sections must say exactly "Not documented."
    Each required_words entry must appear in its assigned section.
    Each forbidden_words entry must be absent from the entire draft as a whole
    word or phrase. Required and forbidden text checks ignore capitalization.

    The printed checklist is for a person to verify meaning, accuracy, and
    whether important details appear in the right section.
    """
    monkeypatch.setenv("DAP_DB_PATH", str(tmp_path / "quality.db"))
    with TestClient(create_app()) as client:
        response = client.post("/reports/generate", json={"notes": notes})

    print(f"\nSource notes: {notes}\nReview: {review}")
    assert response.status_code == 200, response.text
    sections = response.json()["sections"]
    for name, section in sections.items():
        print(f"{name.capitalize()}: {section}")

    # The case lists which sections have no support in the source notes.
    # Each of those sections must use the exact placeholder, including the period.
    for section in missing_sections:
        assert sections[section] == "Not documented.", f"Unexpected {section} text"

    # Each pair names a section and the text expected in that section.
    # For example, {"data": "breathing"} only checks Data for "breathing".
    for section, word in required_words.items():
        assert word in sections[section].casefold()

    # Search all three sections for forbidden text, ignoring capitalization.
    draft_text = "\n".join(sections.values()).casefold()
    for word in forbidden_words:
        # Escape the text so regex treats it literally. Word boundaries keep
        # a name like "Alex" from matching part of a longer word.
        assert not re.search(rf"\b{re.escape(word)}\b", draft_text), word
