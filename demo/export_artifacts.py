"""
Export real workflow artifacts to files — for opening on screen and scrolling
through live, instead of only seeing them fly past in the terminal.

Reuses the exact same classes as triage_demo.py (LogTrimmer, PromptBuilder,
ClaudeClient, ...), so the numbers here always match the numbers the live
terminal demo prints. Nothing is duplicated or re-implemented.

    py export_artifacts.py                    log=test, tries the real API
    py export_artifacts.py --log dependency
    py export_artifacts.py --offline           skip the API, use a saved reply
    py export_artifacts.py --all               generate all four log types

For each log type it writes six files into  demo/log_samples/<type>/:

    00_SUMMARY.txt                    the key numbers, for your own notes
    01_full_ci_log.txt                 the raw ~12,000-line log — open this
                                       one and scroll to show how big it is
    02_trimmed_log_sent_to_model.txt   the ~40 lines actually sent — open
                                       this one right after, side by side
    02b_full_prompt_sent.txt           the complete prompt, log included
    03_model_response.json             the exact JSON the model returned
    04_pr_comment.md                   the final rendered PR comment
"""

import argparse
import json
import os
import sys

import triage_demo as td

HERE = os.path.dirname(os.path.abspath(__file__))


def export_one(kind, offline, outroot):
    outdir = os.path.join(outroot, kind)
    os.makedirs(outdir, exist_ok=True)

    repo, pr = "nmcnpm-2026/demo-shop", "1"
    raw = {
        "_event": "workflow_run", "action": "completed",
        "repository": {"full_name": repo},
        "workflow_run": {
            "id": 8471023, "name": "ci",
            "status": "completed", "conclusion": "failure",
            "head_sha": "3f9c1ab7e42d0091",
            "pull_requests": [{"number": int(pr)}],
        },
    }
    p = td.WebhookPayload.from_dict(raw)

    # ---- the full log --------------------------------------------------
    log_text = td.build_big_log(kind)
    with open(os.path.join(outdir, "01_full_ci_log.txt"), "w",
             encoding="utf-8") as f:
        f.write(log_text)

    # ---- trimmed ---------------------------------------------------------
    trimmed, total, kept, hits = td.LogTrimmer().trim(log_text)
    pct = 100.0 * (total - kept) / total
    header = (
        "====================================================================\n"
        " TRIMMED LOG  -  this is what actually gets sent to Claude\n"
        " {total:,} lines in the original  ->  {kept} lines kept  "
        "({pct:.1f}% removed)  |  {hits} error-pattern matches\n"
        "====================================================================\n\n"
    ).format(total=total, kept=kept, pct=pct, hits=hits)
    with open(os.path.join(outdir, "02_trimmed_log_sent_to_model.txt"), "w",
             encoding="utf-8") as f:
        f.write(header + trimmed)

    user_msg = td.PromptBuilder().build(trimmed, p)
    with open(os.path.join(outdir, "02b_full_prompt_sent.txt"), "w",
             encoding="utf-8") as f:
        f.write(user_msg)

    # ---- the model call ---------------------------------------------------
    usage = None
    if offline or not os.environ.get("ANTHROPIC_API_KEY"):
        data = td.CANNED[kind]
        source = "OFFLINE — saved response (no API key / --offline set)"
    else:
        try:
            data, usage, _btype = td.ClaudeClient().complete(user_msg)
            source = "LIVE — real Claude API call"
        except Exception as e:
            print("  ! API call failed (%s) — falling back to saved response"
                 % e)
            data = td.CANNED[kind]
            source = "OFFLINE — saved response (API call failed)"

    with open(os.path.join(outdir, "03_model_response.json"), "w",
             encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # ---- validation + final comment ---------------------------------------
    checks = td.ResponseValidator().checks(data)
    result = td.TriageResult(p, data)
    comment = td.MarkdownFormatter().format(result)
    with open(os.path.join(outdir, "04_pr_comment.md"), "w",
             encoding="utf-8") as f:
        f.write(comment)

    # ---- summary ------------------------------------------------------
    lines = [
        "CI FAILURE TRIAGE — artifact summary",
        "log type      : %s" % kind,
        "source        : %s" % source,
        "",
        "full log      : {:,} lines, {:.0f} KB".format(
            total, len(log_text.encode("utf-8")) / 1024.0),
        "trimmed log   : %d lines (%.1f%% removed), %d pattern matches"
        % (kept, pct, hits),
        "prompt sent   : {:,} characters".format(len(user_msg)),
    ]
    if usage:
        lines.append("tokens        : %s in / %s out"
                     % (usage.input_tokens, usage.output_tokens))
    lines += ["", "category      : %s" % data["failure_category"],
             "confidence    : %s" % data["confidence_score"],
             "validation    : %d/%d rules passed"
             % (sum(1 for _, ok, _ in checks if ok), len(checks))]
    with open(os.path.join(outdir, "00_SUMMARY.txt"), "w",
             encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("  [%-10s] %s   (%s)" % (kind, outdir, source))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="test",
                    choices=["test", "dependency", "syntax", "timeout"])
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--all", action="store_true",
                    help="generate all four log types")
    ap.add_argument("--out", default=os.path.join(HERE, "log_samples"))
    args = ap.parse_args()

    kinds = ["test", "dependency", "syntax", "timeout"] if args.all else [args.log]
    print("")
    for k in kinds:
        export_one(k, args.offline, args.out)
    print("\nDone. Open the files under:\n  %s\n" % args.out)
    print("Suggested order to show on screen:")
    print("  1. open 01_full_ci_log.txt  — scroll fast, let it look huge")
    print("  2. open 02_trimmed_log_sent_to_model.txt  — the tiny result")
    print("  3. open 03_model_response.json  — what came back")
    print("  4. open 04_pr_comment.md  — what the developer actually sees")


if __name__ == "__main__":
    main()
