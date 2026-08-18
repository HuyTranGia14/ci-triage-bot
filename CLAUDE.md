# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

**CI Failure Triage Bot** — a course project (course: "Introduction to Software Engineering", ticket-tracked as NMCNPM-*). Intended end state: a GitHub webhook bot that, when a CI workflow run fails, fetches the run's logs, trims them, sends them to Claude with a forced structured-output schema, validates the response, and posts a triage comment (failure category, confidence, root cause, suggested fix) on the associated pull request.

**Current state: this is a demo/spike-stage project, not a deployed service.** There is no HTTP server, no webhook receiver, no persistence layer, and no automated test suite anywhere in the repo. What exists is a single-file reference implementation (`demo/triage_demo.py`) that runs the full pipeline end-to-end against a synthesized (not live) GitHub event, plus a throwaway spike (`spike/`) that was used to empirically decide a design question before writing it up. Team: Trần Gia Huy (lead), Nguyễn Hoàng Danh, Vũ Mạnh Quân.

## Repository layout

```
spike/     throwaway engineering spike (ticket NMCNPM-43) — NOT part of the product, has its own venv
demo/      the actual reference implementation — all pipeline classes live here
seminar/   slide deck + speaker scripts for the graded oral presentation — not runtime code
diagrams/  4 SVG design diagrams (class diagram, conceptual model, data model, decomposition tree) —
           the closest thing this repo has to a written design doc
```

There is no `src/`, `app/`, `requirements.txt`, `pyproject.toml`, or config/CI files at the repo root. Dependencies are documented only inline (see Commands below). The only third-party dependency for the actual bot logic is `anthropic`; `seminar/` additionally needs `python-pptx` and `reportlab`, which are unrelated to the bot itself.

**Windows note:** on the primary dev machine, the `python` command resolves to a broken MSYS2 install with no working `pip`. Always use `py` instead of `python` for every command below.

## Commands

Run the reference pipeline (`demo/triage_demo.py`):
```powershell
cd demo
py -m pip install anthropic
py triage_demo.py --offline                        # no network, canned response — always works
py triage_demo.py                                   # live call, needs ANTHROPIC_API_KEY env var
py triage_demo.py --focus 5,7 --step                # expand steps 5 & 7 in full detail, pause on Enter between steps
py triage_demo.py --log dependency|syntax|timeout    # try a different synthetic failure type (default: test)
py triage_demo.py --post                             # actually POST a PR comment (needs GH_TOKEN, GH_REPO=owner/name, GH_PR=1)
py triage_demo.py --no-color
```
Without `--post`, the rendered comment is written to `demo/comment.md` instead of being sent anywhere.

Export each pipeline stage to inspectable files (reuses `triage_demo.py`'s classes directly, so numbers always match the live run):
```powershell
cd demo
py export_artifacts.py --log test|dependency|syntax|timeout [--offline] [--all]
```
Writes `00_SUMMARY.txt`, `01_full_ci_log.txt`, `02_trimmed_log_sent_to_model.txt`, `02b_full_prompt_sent.txt`, `03_model_response.json`, `04_pr_comment.md` into `demo/log_samples/<type>/`.

Run the spike (compares prompt-only vs. tool-based JSON enforcement, 4 sample logs × N runs × 2 modes):
```powershell
cd spike
.\venv\Scripts\Activate.ps1          # a venv is already checked in here
$env:ANTHROPIC_API_KEY = "sk-ant-..."
py run_spike.py --runs 5             # --runs 2 for a cheap smoke test; --runs 5 = 40 API calls total
py debug_trace.py                    # one-shot: prints full raw request/response for both modes on one sample log
```

There is no test suite (no `pytest`, no `test_*.py` owned by this project) — "testing" so far means running the spike above and reading its printed pass-rate table.

Build the seminar deck / PDFs (unrelated to the bot's runtime, only relevant if working on presentation materials):
```powershell
cd seminar
py -m pip install python-pptx && py build_deck.py          # -> Seminar_Topic8_AI_Assisted_DevOps.pptx
py -m pip install reportlab && py build_script_pdf.py all  # regenerate all script PDFs from their .md sources
```

## Architecture

**All pipeline classes live in one file: `demo/triage_demo.py`.** There is no separate production source tree — this file *is* the canonical implementation, named and ordered to match the class diagram in `diagrams/class_diagram.svg`:

`WebhookPayload` (DTO, `.from_dict()`) → `SignatureVerifier` (HMAC-SHA256, uses `hmac.compare_digest` — not `==` — to avoid timing attacks) → `EventFilter` (3-condition gate: event/status/conclusion) → `LogTrimmer` (keeps last 40 lines + lines matching 10 error-pattern regexes ± 3 lines context, capped at 60 kept lines) → `PromptBuilder` → `ClaudeClient` (forces structured output via `tool_choice={"type":"tool","name":...}`, not prompt-only JSON) → `ResponseValidator` (6 checks) → `TriageResult` (DTO) → `MarkdownFormatter` → `GitHubClient.post_pr_comment()` (plain `urllib.request`, no HTTP library dependency).

The triage schema (`failure_category` enum, `confidence_score`, `root_cause`, `suggested_fix`) is defined identically in two places that must be kept in sync: `spike/triage_schema.json` and the `SCHEMA` dict inside `demo/triage_demo.py`. **Key gotcha carried through the whole design:** the schema's `confidence_score` range and the 600-character limits on `root_cause`/`suggested_fix` are only prose inside the JSON Schema `description` fields — the API does not actually enforce them (no real `minimum`/`maximum`/`maxLength`). This is why `ResponseValidator` exists and runs even though output is already schema-conformant by construction.

**The class diagram describes more than is implemented.** `diagrams/class_diagram.svg`, `conceptual_model_diagram.svg`, `data_diagram.svg`, and `system_decomposition_tree.svg` together document a fuller design — `WebhookController`, `DashboardController`, `ConfigManager`, `TriageService` (as an actual orchestrator class), `HistoryStore`, `RepoManager`, `RepositoryConfig`, plus a Postgres-style relational schema (`repository_config`, `triage_result` tables). **None of these exist in code.** In `demo/triage_demo.py`, the orchestration role of `TriageService.process_failed_run()` is played procedurally by the `run(args)` function; there is no HTTP receiver, no persistence, no dashboard, and no `run_id` idempotency check. Treat the diagrams as the target design, not as a description of what's implemented — when picking up work here, check whether a class from the diagram already exists in `triage_demo.py` before assuming it does.

`demo/triage_demo.py` also contains `build_big_log(kind)`, which deterministically generates a realistic ~12,000-line synthetic GitHub Actions log (seeded RNG) for each of 4 failure types (`test`, `dependency`, `syntax`, `timeout`) — this is what stands in for a real fetched CI log throughout the demo and spike, since there is no live webhook/repo integration yet.

`seminar/` and `diagrams/` are presentation/design artifacts, not code the bot depends on at runtime — don't wire them into the pipeline.
