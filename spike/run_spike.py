"""NMCNPM-43 spike: does Claude actually return our triage schema?

Runs every sample log through the Claude API twice: once asking for JSON in
the prompt only, once forcing the schema through the tool mechanism. Reports
how often each approach produced valid, schema-conformant output and how
often the category was correct.

Usage:
    set ANTHROPIC_API_KEY=sk-ant-...        (PowerShell: $env:ANTHROPIC_API_KEY="...")
    python run_spike.py                     5 runs per log per mode
    python run_spike.py --runs 3            fewer runs, cheaper
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    from anthropic import Anthropic
except ImportError:
    sys.exit("Missing dependency. Run: pip install anthropic")


HERE = Path(__file__).parent
SCHEMA_FILE = HERE / "triage_schema.json"
SAMPLES_DIR = HERE / "samples"
MODEL = os.environ.get("SPIKE_MODEL", "claude-sonnet-5")

# Ground truth: the category a correct triage should return for each sample.
EXPECTED = {
    "dependency_issue.log": "dependency_issue",
    "test_failure.log": "test_failure",
    "syntax_error.log": "syntax_error",
    "infrastructure_timeout.log": "infrastructure_timeout",
}

SYSTEM_PROMPT = (
    "You are a CI failure triage assistant. You are given the tail of a failed "
    "continuous integration job log. Identify why the job failed, basing your "
    "answer on the actual error text in the log rather than on generic advice."
)


def load_schema() -> dict:
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))


def build_user_message(log_text: str, schema: dict, ask_for_json: bool) -> str:
    parts = [
        "Analyse the following failed CI job log.",
        "",
        "```",
        log_text.strip(),
        "```",
    ]
    if ask_for_json:
        parts += [
            "",
            "Reply with a single JSON object and nothing else. No prose, no "
            "explanation, no Markdown code fence. The object must match this "
            "schema exactly:",
            json.dumps(schema["input_schema"], indent=2),
        ]
    return "\n".join(parts)


# --------------------------------------------------------------------------
# Validation (mirrors what ResponseValidator will do in production)
# --------------------------------------------------------------------------

def extract_json(text: str) -> dict | None:
    """Pull a JSON object out of raw model text, tolerating code fences."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else None

    if candidate is None:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end < start:
            return None
        candidate = text[start : end + 1]

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def validate(payload: dict, schema: dict) -> list[str]:
    """Return a list of violations. Empty list means the payload conforms."""
    spec = schema["input_schema"]
    props = spec["properties"]
    problems: list[str] = []

    for field in spec["required"]:
        if field not in payload:
            problems.append(f"missing field '{field}'")

    for field in payload:
        if field not in props:
            problems.append(f"unexpected field '{field}'")

    category = payload.get("failure_category")
    if category is not None and category not in props["failure_category"]["enum"]:
        problems.append(f"category '{category}' is outside the enum")

    score = payload.get("confidence_score")
    if score is not None:
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            problems.append("confidence_score is not a number")
        elif not 0.0 <= float(score) <= 1.0:
            problems.append(f"confidence_score {score} outside [0, 1]")

    for field in ("root_cause", "suggested_fix"):
        value = payload.get(field)
        if value is not None:
            if not isinstance(value, str):
                problems.append(f"{field} is not a string")
            elif len(value) > 600:
                problems.append(f"{field} exceeds 600 characters")

    return problems


# --------------------------------------------------------------------------
# The two enforcement approaches
# --------------------------------------------------------------------------

def call_prompt_only(client: Anthropic, log_text: str, schema: dict):
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": build_user_message(log_text, schema, ask_for_json=True),
            }
        ],
    )
    text = "".join(
        block.text for block in response.content if block.type == "text"
    )
    return extract_json(text), text


def call_tool_based(client: Anthropic, log_text: str, schema: dict):
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        tools=[
            {
                "name": schema["name"],
                "description": schema["description"],
                "input_schema": schema["input_schema"],
            }
        ],
        tool_choice={"type": "tool", "name": schema["name"]},
        messages=[
            {
                "role": "user",
                "content": build_user_message(log_text, schema, ask_for_json=False),
            }
        ],
    )
    for block in response.content:
        if block.type == "tool_use":
            return block.input, json.dumps(block.input)
    return None, "no tool_use block returned"


MODES = {
    "prompt-only": call_prompt_only,
    "tool-based": call_tool_based,
}


# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5, help="runs per log per mode")
    parser.add_argument("--verbose", action="store_true", help="print every failure")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set.")

    schema = load_schema()
    logs = sorted(SAMPLES_DIR.glob("*.log"))
    if not logs:
        sys.exit(f"No .log files found in {SAMPLES_DIR}")

    client = Anthropic()
    totals = {
        mode: {"runs": 0, "parsed": 0, "conformant": 0, "correct": 0}
        for mode in MODES
    }

    for mode, call in MODES.items():
        print(f"\n=== {mode} ===")
        for log_path in logs:
            log_text = log_path.read_text(encoding="utf-8")
            expected = EXPECTED.get(log_path.name)

            for attempt in range(1, args.runs + 1):
                stats = totals[mode]
                stats["runs"] += 1
                try:
                    payload, raw = call(client, log_text, schema)
                except Exception as error:  # transport / rate limit
                    print(f"  {log_path.name} #{attempt}: API error - {error}")
                    time.sleep(2)
                    continue

                if payload is None:
                    print(f"  {log_path.name} #{attempt}: no JSON could be parsed")
                    if args.verbose:
                        print(f"    raw: {raw[:200]}")
                    continue
                stats["parsed"] += 1

                problems = validate(payload, schema)
                if problems:
                    print(f"  {log_path.name} #{attempt}: {'; '.join(problems)}")
                    continue
                stats["conformant"] += 1

                got = payload["failure_category"]
                if expected is None:
                    continue
                if got == expected:
                    stats["correct"] += 1
                    print(f"  {log_path.name} #{attempt}: OK ({got})")
                else:
                    print(
                        f"  {log_path.name} #{attempt}: conformant but "
                        f"category {got}, expected {expected}"
                    )

    print("\n\n## Results (paste into section 4.2)\n")
    print("| Enforcement | Runs | Valid JSON | Schema-conformant | Category correct |")
    print("|---|---|---|---|---|")
    for mode, s in totals.items():
        runs = s["runs"] or 1
        print(
            f"| {mode} | {s['runs']} | "
            f"{s['parsed']} ({100 * s['parsed'] // runs}%) | "
            f"{s['conformant']} ({100 * s['conformant'] // runs}%) | "
            f"{s['correct']} ({100 * s['correct'] // runs}%) |"
        )
    print(f"\nModel: {MODEL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
