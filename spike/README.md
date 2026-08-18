# Spike NMCNPM-43 — validating the triage JSON schema

Purpose: before the JSON schema is written into section 4.2 of the design
document, check empirically that the Claude API really returns data that
conforms to it, and decide which enforcement mechanism the implementation
should use.

This is throwaway code. It is not part of the product and does not need to
be merged.

## Setup

```powershell
cd D:\CI_Failure_Triage_Bot\spike
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install anthropic
$env:ANTHROPIC_API_KEY = "sk-ant-..."
```

## Run

```powershell
python run_spike.py --runs 5
```

Five runs per log per mode over four logs is 40 API calls. Start with
`--runs 2` to check everything works before spending the full budget.

## What it compares

**prompt-only** asks for a JSON object in the user message and then tries
to parse whatever text comes back.

**tool-based** declares the schema as a tool and forces the model to call
it, so the API returns an already-parsed object.

Both go through the same validator, which is a deliberate miniature of the
`ResponseValidator` class in section 3.3.9: required fields present, no
extra fields, `failure_category` inside the enum, `confidence_score` a
number in [0, 1], text fields under 600 characters.

## What to record

The script prints a Markdown table at the end. Paste it into section 4.2
and state which mechanism the implementation will use. If tool-based
reaches 100% conformance and prompt-only does not, that is the evidence
justifying the `strict = true` constraint already written into 3.3.9.

Note the ground-truth categories in `EXPECTED` inside `run_spike.py` are a
judgement call. `test_failure.log` is a genuine assertion failure caused by
floating-point arithmetic, so `test_failure` is correct and `flaky_test`
is wrong — a flaky test is one that passes and fails without the code
changing. Expect the model to occasionally disagree; record that as a
finding rather than as a bug.
