import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ci_demo.py"


def test_cli_accepts_notes_and_emits_json(tmp_path):
    notes = "Synthetic student said: 'I feel unsure.'"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--notes", notes],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert result.stderr == ""
    assert json.loads(result.stdout) == {
        "data": notes,
        "assessment": "Not documented.",
        "plan": "Not documented.",
    }


def test_cli_rejects_unknown_arguments(tmp_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--unknown-option"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr
    assert result.stdout == ""
