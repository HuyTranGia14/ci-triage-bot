"""One-off trace: show exactly what goes IN to the API and what comes OUT.

Runs a single log (dependency_issue.log) through both modes, once each,
and prints the full request payload and the full raw response — no
aggregation, no stats, just the raw data for inspection.

Usage:
    $env:ANTHROPIC_API_KEY = "sk-ant-..."
    python debug_trace.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

try:
    from anthropic import Anthropic
except ImportError:
    sys.exit("Missing dependency. Run: pip install anthropic")

HERE = Path(__file__).parent
SCHEMA_FILE = HERE / "triage_schema.json"
LOG_FILE = HERE / "samples" / "dependency_issue.log"
MODEL = os.environ.get("SPIKE_MODEL", "claude-sonnet-5")

SYSTEM_PROMPT = (
    "You are a CI failure triage assistant. You are given the tail of a failed "
    "continuous integration job log. Identify why the job failed, basing your "
    "answer on the actual error text in the log rather than on generic advice."
)


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


def section(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set.")

    schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    log_text = LOG_FILE.read_text(encoding="utf-8")
    client = Anthropic()

    # ---------------- prompt-only ----------------
    user_msg_prompt_only = build_user_message(log_text, schema, ask_for_json=True)
    request_prompt_only = {
        "model": MODEL,
        "max_tokens": 1024,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_msg_prompt_only}],
    }

    section("PROMPT-ONLY — REQUEST BODY SENT TO THE API")
    print(json.dumps(request_prompt_only, indent=2)[:3000])

    response = client.messages.create(**request_prompt_only)
    raw_text = "".join(b.text for b in response.content if b.type == "text")

    section("PROMPT-ONLY — RAW RESPONSE TEXT")
    print(raw_text)

    section("PROMPT-ONLY — response.usage (tokens actually billed)")
    print(response.usage)

    # ---------------- tool-based ----------------
    user_msg_tool = build_user_message(log_text, schema, ask_for_json=False)
    request_tool_based = {
        "model": MODEL,
        "max_tokens": 1024,
        "system": SYSTEM_PROMPT,
        "tools": [
            {
                "name": schema["name"],
                "description": schema["description"],
                "input_schema": schema["input_schema"],
            }
        ],
        "tool_choice": {"type": "tool", "name": schema["name"]},
        "messages": [{"role": "user", "content": user_msg_tool}],
    }

    section("TOOL-BASED — REQUEST BODY SENT TO THE API")
    print(json.dumps(request_tool_based, indent=2)[:3000])

    response2 = client.messages.create(**request_tool_based)

    section("TOOL-BASED — FULL response.content (all blocks)")
    for block in response2.content:
        print(f"  block.type = {block.type}")
        if block.type == "tool_use":
            print("  block.input (already-parsed dict, no JSON parsing needed):")
            print(json.dumps(block.input, indent=2))
        elif block.type == "text":
            print(f"  block.text = {block.text!r}")

    section("TOOL-BASED — response.usage (tokens actually billed)")
    print(response2.usage)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
