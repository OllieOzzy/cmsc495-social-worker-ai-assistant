"""Deterministic CI example, not an LLM or the application report generator."""

import argparse
import json


def build_demo_report(notes: str) -> dict[str, str]:
    """Copy notes into Data without inferring an assessment or plan."""
    return {
        "data": notes.strip() or "Not documented.",
        "assessment": "Not documented.",
        "plan": "Not documented.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notes", default="", help="Synthetic notes for the CI demo")
    args = parser.parse_args()
    print(json.dumps(build_demo_report(args.notes)))


if __name__ == "__main__":
    main()