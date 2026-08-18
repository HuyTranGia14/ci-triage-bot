"""
CI Failure Triage Bot — end-to-end workflow demo.

Runs all nine pipeline steps from the design document, in order, and shows
the data crossing every boundary: the raw webhook, the signature bytes, the
filter conditions, the log before and after trimming, the exact prompt, the
exact API request, the raw response block, and every validation rule.

    py -m pip install anthropic
    $env:ANTHROPIC_API_KEY = "sk-ant-..."
    py triage_demo.py

For presenting (recommended):

    py triage_demo.py --step                 pause for Enter between steps
    py triage_demo.py --focus all --step     show every step in full detail

Flags
    --focus 5,7      which steps to expand in full   (default: 5,7)
                     use "all" for everything, "none" for the compact run
    --step           wait for Enter between steps — you control the pace
    --offline        no network at all; uses a saved model response
    --post           POST the comment to a GitHub PR
                     (needs GH_TOKEN, GH_REPO=owner/name, GH_PR=1)
    --log NAME       dependency | test | syntax | timeout   (default: test)
    --no-color

Only dependency is `anthropic`. Everything else is the standard library.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.environ.get("SPIKE_MODEL", "claude-sonnet-5")
WEBHOOK_SECRET = b"demo-shared-secret-not-a-real-one"
BOXW = 76

if os.name == "nt":
    os.system("")          # enable ANSI escapes on modern Windows

_USE_COLOR = True
_FOCUS = set()
_PAUSE = False


# --------------------------------------------------------------------------
# terminal helpers
# --------------------------------------------------------------------------
def c(t, code):
    return t if not _USE_COLOR else "\033[%sm%s\033[0m" % (code, t)


def dim(t):    return c(t, "90")
def red(t):    return c(t, "91")
def green(t):  return c(t, "92")
def yellow(t): return c(t, "93")
def blue(t):   return c(t, "96")
def mag(t):    return c(t, "95")
def bold(t):   return c(t, "1")


ANSI = re.compile(r"\033\[[0-9;]*m")


def vlen(s):
    return len(ANSI.sub("", s))


def clip(s, w):
    """Truncate to w visible characters, keeping colour codes intact."""
    if vlen(s) <= w:
        return s
    out, n = [], 0
    i = 0
    while i < len(s) and n < w - 1:
        m = ANSI.match(s, i)
        if m:
            out.append(m.group(0))
            i = m.end()
            continue
        out.append(s[i])
        n += 1
        i += 1
    return "".join(out) + dim("…")


def box(title, lines, color=dim):
    print("   " + color("┌─ " + title + " " + "─" * max(0, BOXW - 5 - len(title)) + "┐"))
    for ln in lines:
        ln = clip(ln, BOXW - 4)
        print("   " + color("│ ") + ln + " " * (BOXW - 4 - vlen(ln)) + color(" │"))
    print("   " + color("└" + "─" * (BOXW - 2) + "┘"))


def kv(k, v):
    print("   %-9s %s" % (dim(k), v))


def rule(t=""):
    if t:
        print(dim("── " + t + " " + "─" * max(0, BOXW + 3 - len(t))))
    else:
        print(dim("─" * (BOXW + 6)))


def gate():
    if _PAUSE:
        try:
            input(dim("        ⏎ "))
        except (EOFError, KeyboardInterrupt):
            print("")
            raise SystemExit(0)


class Step:
    """Times a pipeline step and prints it compact or expanded."""

    def __init__(self, n, cls, method, why):
        self.n, self.cls, self.method, self.why = n, cls, method, why
        self.full = (n in _FOCUS)

    def __enter__(self):
        self.t = time.time()
        if self.full:
            print("")
            print(mag("━━ STEP %d " % self.n) + bold("%s.%s()" % (self.cls, self.method))
                  + " " + mag("━" * max(0, BOXW - 14 - len(self.cls) - len(self.method))))
            kv("why", dim(self.why))
        return self

    def done(self, summary, ok=True):
        el = time.time() - self.t
        if self.full:
            kv("time", dim("%.3fs" % el))
        else:
            tag = green("[%d/9]" % self.n) if ok else red("[%d/9]" % self.n)
            print("%s %-20s %s  %s"
                  % (tag, bold(self.cls), summary, dim("%6.3fs" % el)))
        gate()

    def __exit__(self, *a):
        return False


# --------------------------------------------------------------------------
# the triage schema  (section 4.2 of the design document)
# --------------------------------------------------------------------------
SCHEMA = {
    "name": "triage_result",
    "description": "Structured triage report for a failed CI job.",
    "input_schema": {
        "type": "object",
        "properties": {
            "failure_category": {
                "type": "string",
                "enum": ["flaky_test", "test_failure", "dependency_issue",
                         "syntax_error", "configuration_error",
                         "infrastructure_timeout", "unknown"],
                "description": "The single category that best describes the "
                               "root cause of this CI failure.",
            },
            "confidence_score": {
                "type": "number",
                "description": "Confidence in the assigned category, 0.0 to 1.0.",
            },
            "root_cause": {
                "type": "string",
                "description": "Plain-English explanation of why the job "
                               "failed. Must reference the actual error text "
                               "found in the log. Maximum 600 characters.",
            },
            "suggested_fix": {
                "type": "string",
                "description": "One concrete, actionable fix tied to the "
                               "specific error in the log. Maximum 600 "
                               "characters.",
            },
        },
        "required": ["failure_category", "confidence_score",
                     "root_cause", "suggested_fix"],
    },
}

SYSTEM_PROMPT = (
    "You are a CI failure triage assistant. You are given the tail of a failed "
    "continuous integration job log. Identify why the job failed, basing your "
    "answer on the actual error text in the log rather than on generic advice."
)


# --------------------------------------------------------------------------
# step 4 — a realistic 12,000-line GitHub Actions log
# --------------------------------------------------------------------------
FAILURES = {
    "test": [
        "=================================== FAILURES ===================================",
        "___________________________ test_cart_total_rounding ___________________________",
        "tests/test_cart.py:87: in test_cart_total_rounding",
        "    assert cart.total() == 19.99",
        "E   assert 19.990000000000002 == 19.99",
        "E    +  where 19.990000000000002 = <bound method Cart.total of <src.cart.Cart object>>()",
        "src/cart.py:42: in total",
        "    return sum(item.price * item.quantity for item in self._items)",
        "=========================== short test summary info ============================",
        "FAILED tests/test_cart.py::test_cart_total_rounding - assert 19.990000000000002 == 19.99",
        "======================== 1 failed, 127 passed in 20.22s ========================",
        "##[error]Process completed with exit code 1.",
    ],
    "dependency": [
        "##[group]Run pip install -r requirements.txt",
        "Collecting requests-toolbelt==1.0.9",
        "ERROR: Could not find a version that satisfies the requirement "
        "requests-toolbelt==1.0.9 (from versions: 0.9.1, 1.0.0)",
        "ERROR: No matching distribution found for requests-toolbelt==1.0.9",
        "##[error]Process completed with exit code 1.",
    ],
    "syntax": [
        "##[group]Run python -m compileall src",
        '  File "src/checkout.py", line 118',
        "    if user.is_active and user.has_card()",
        "                                        ^",
        "SyntaxError: expected ':'",
        "##[error]Process completed with exit code 1.",
    ],
    "timeout": [
        "##[group]Run pytest tests/integration",
        "tests/integration/test_payments.py::test_charge ",
        "The runner has received a shutdown signal.",
        "##[error]The operation was canceled.",
        "##[error]The job running on runner GitHub Actions 12 has exceeded the "
        "maximum execution time of 360 minutes.",
    ],
}

NOISE = [
    "Requirement already satisfied: {p} in /opt/hostedtoolcache/Python/3.11.9/x64/lib",
    "tests/test_{m}.py::test_{f} PASSED                                    [ {pct}%]",
    "##[debug]Evaluating condition for step: 'Run {m}'",
    "Downloading {p}-{v}-py3-none-any.whl (2{n} kB)",
    "  Installing collected packages: {p}",
    "##[debug]Result: true",
    "  Building wheel for {p} (setup.py): started",
    "Cache restored from key: setup-python-Linux-x64-pip-{n}a3f9c",
]
WORDS = ["cart", "orders", "checkout", "billing", "users", "auth", "catalog",
         "shipping", "search", "reviews", "inventory", "notifications"]


def build_big_log(kind):
    import random
    rnd = random.Random(20260812)
    out = ["2026-08-12T04:02:09.1120043Z ##[group]Operating System",
           "2026-08-12T04:02:09.1120044Z Ubuntu 22.04.4 LTS",
           "2026-08-12T04:02:09.1120045Z ##[endgroup]",
           "2026-08-12T04:02:11.0031244Z ##[group]Run pytest -v --tb=short",
           "2026-08-12T04:02:12.7782110Z platform linux -- Python 3.11.9, pytest-8.2.0"]
    t = 12.0
    for i in range(12000):
        tpl = NOISE[i % len(NOISE)]
        line = (tpl.replace("{p}", rnd.choice(WORDS) + "-lib")
                   .replace("{m}", rnd.choice(WORDS))
                   .replace("{f}", rnd.choice(WORDS))
                   .replace("{pct}", str(min(99, i * 100 // 12000)))
                   .replace("{v}", "%d.%d.%d" % (rnd.randint(0, 4), rnd.randint(0, 9),
                                                 rnd.randint(0, 9)))
                   .replace("{n}", str(rnd.randint(1, 9))))
        t += 0.0016
        out.append("2026-08-12T04:%02d:%05.2fZ %s" % (2 + int(t // 60), t % 60, line))
    for line in FAILURES[kind]:
        t += 0.02
        out.append("2026-08-12T04:%02d:%05.2fZ %s" % (2 + int(t // 60), t % 60, line))
    return "\n".join(out)


# --------------------------------------------------------------------------
# pipeline classes  (names match the PA2 class diagram)
# --------------------------------------------------------------------------
class WebhookPayload:
    def __init__(self, event, action, status, conclusion, run_id, repo,
                 pr_number, head_sha):
        self.event, self.action = event, action
        self.status, self.conclusion = status, conclusion
        self.run_id, self.repo = run_id, repo
        self.pr_number, self.head_sha = pr_number, head_sha

    @classmethod
    def from_dict(cls, d):
        wr = d.get("workflow_run", {})
        prs = wr.get("pull_requests") or [{}]
        return cls(event=d.get("_event", "workflow_run"),
                   action=d.get("action"),
                   status=wr.get("status"),
                   conclusion=wr.get("conclusion"),
                   run_id=wr.get("id"),
                   repo=d.get("repository", {}).get("full_name"),
                   pr_number=prs[0].get("number"),
                   head_sha=(wr.get("head_sha") or "")[:7])


class SignatureVerifier:
    def __init__(self, secret):
        self.secret = secret

    def sign(self, body):
        return "sha256=" + hmac.new(self.secret, body, hashlib.sha256).hexdigest()

    def verify(self, body, header):
        return hmac.compare_digest(self.sign(body), header or "")


class EventFilter:
    TARGET_EVENT = "workflow_run"
    TARGET_STATUS = "completed"
    TARGET_CONCLUSION = "failure"

    def conditions(self, p):
        return [("event", self.TARGET_EVENT, p.event),
                ("status", self.TARGET_STATUS, p.status),
                ("conclusion", self.TARGET_CONCLUSION, p.conclusion)]

    def is_valid_failure_event(self, p):
        return all(exp == got for _, exp, got in self.conditions(p))


class LogTrimmer:
    PATTERNS = [r"##\[error\]", r"^\s*E\s", r"\bFAILED\b", r"Traceback",
                r"\bERROR\b", r"fatal:", r"Exception", r"SyntaxError",
                r"was canceled", r"exceeded the maximum"]

    def __init__(self, tail=40, context=3, max_lines=60):
        self.tail, self.context, self.max_lines = tail, context, max_lines
        self._rx = re.compile("|".join(self.PATTERNS))

    def trim(self, text):
        lines = text.split("\n")
        tail_idx = set(range(max(0, len(lines) - self.tail), len(lines)))
        hits = [i for i, ln in enumerate(lines) if self._rx.search(ln)]
        keep = set(tail_idx)
        for i in hits:
            for j in range(max(0, i - self.context),
                           min(len(lines), i + self.context + 1)):
                keep.add(j)
        idx = sorted(keep)[-self.max_lines:]
        out, prev = [], None
        for i in idx:
            if prev is not None and i > prev + 1:
                out.append("        ... %d lines omitted ..." % (i - prev - 1))
            out.append(lines[i])
            prev = i
        return "\n".join(out), len(lines), len(idx), len(hits)


class PromptBuilder:
    def build(self, log_text, payload):
        return ("Analyse the following failed CI job log.\n\n"
                "Repository: %s\nWorkflow run: %s\nCommit: %s\n\n"
                "```\n%s\n```" % (payload.repo, payload.run_id,
                                  payload.head_sha, log_text.strip()))


class ClaudeClient:
    def __init__(self, model=MODEL, max_tokens=1024):
        from anthropic import Anthropic
        self.client = Anthropic()
        self.model = model
        self.max_tokens = max_tokens

    def request_shape(self, user_message):
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": "<%d chars>" % len(SYSTEM_PROMPT),
            "tools": [{"name": SCHEMA["name"],
                       "input_schema": "<4 properties, 1 enum of 7>"}],
            "tool_choice": {"type": "tool", "name": SCHEMA["name"]},
            "messages": [{"role": "user",
                          "content": "<%d chars>" % len(user_message)}],
        }

    def complete(self, user_message):
        resp = self.client.messages.create(
            model=self.model, max_tokens=self.max_tokens, system=SYSTEM_PROMPT,
            tools=[{"name": SCHEMA["name"],
                    "description": SCHEMA["description"],
                    "input_schema": SCHEMA["input_schema"]}],
            tool_choice={"type": "tool", "name": SCHEMA["name"]},
            messages=[{"role": "user", "content": user_message}])
        for block in resp.content:
            if block.type == "tool_use":
                return block.input, resp.usage, block.type
        raise RuntimeError("no tool_use block in the response")


CANNED = {
    "test": {
        "failure_category": "test_failure",
        "confidence_score": 0.95,
        "root_cause": "tests/test_cart.py:87 asserts cart.total() == 19.99, but "
                      "Cart.total() in src/cart.py:42 sums float prices and "
                      "returns 19.990000000000002. Binary floating point cannot "
                      "represent these decimal prices exactly, so the sum drifts "
                      "by a fraction of a cent and the equality assertion fails.",
        "suggested_fix": "Compare with a tolerance using pytest.approx(19.99), "
                         "or better, store and accumulate prices as "
                         "decimal.Decimal in src/cart.py:42 so money arithmetic "
                         "is exact.",
    },
    "dependency": {
        "failure_category": "dependency_issue",
        "confidence_score": 0.97,
        "root_cause": "pip could not resolve requests-toolbelt==1.0.9. The index "
                      "reports only 0.9.1 and 1.0.0 as available, so the pinned "
                      "version does not exist.",
        "suggested_fix": "Pin requests-toolbelt==1.0.0 in requirements.txt, or "
                         "relax the pin to >=1.0,<2.0.",
    },
    "syntax": {
        "failure_category": "syntax_error",
        "confidence_score": 0.99,
        "root_cause": "src/checkout.py line 118 opens an if statement but never "
                      "closes it with a colon, so compileall aborts with "
                      "SyntaxError: expected ':'.",
        "suggested_fix": "Add the missing colon at the end of line 118: "
                         "'if user.is_active and user.has_card():'",
    },
    "timeout": {
        "failure_category": "infrastructure_timeout",
        "confidence_score": 0.9,
        "root_cause": "The job was cancelled by the runner after exceeding the "
                      "360-minute maximum execution time while running "
                      "tests/integration/test_payments.py::test_charge.",
        "suggested_fix": "Add a per-test timeout to the integration suite and "
                         "check whether test_charge is waiting on a payment "
                         "sandbox that never responds.",
    },
}


class ResponseValidator:
    def checks(self, payload):
        spec = SCHEMA["input_schema"]
        props = spec["properties"]
        out = []
        missing = [f for f in spec["required"] if f not in payload]
        out.append(("all 4 required fields present", not missing,
                    "missing " + ", ".join(missing) if missing else "4/4"))
        extra = [f for f in payload if f not in props]
        out.append(("no unexpected fields", not extra,
                    "extra " + ", ".join(extra) if extra else "none"))
        cat = payload.get("failure_category")
        out.append(("failure_category in the 7-value enum",
                    cat in props["failure_category"]["enum"], str(cat)))
        sc = payload.get("confidence_score")
        ok_sc = (isinstance(sc, (int, float)) and not isinstance(sc, bool)
                 and 0.0 <= float(sc) <= 1.0)
        out.append(("confidence_score is a number in [0,1]", ok_sc, str(sc)))
        for f in ("root_cause", "suggested_fix"):
            v = payload.get(f, "")
            out.append(("%s under 600 chars" % f,
                        isinstance(v, str) and len(v) <= 600,
                        "%d chars" % len(v) if isinstance(v, str) else "not a string"))
        return out

    def validate(self, payload):
        return [name for name, ok, _ in self.checks(payload) if not ok]


class TriageResult:
    def __init__(self, payload, data):
        self.repository = payload.repo
        self.run_id = payload.run_id
        self.pr_number = payload.pr_number
        self.failure_category = data["failure_category"]
        self.confidence_score = data["confidence_score"]
        self.root_cause = data["root_cause"]
        self.suggested_fix = data["suggested_fix"]
        self.comment_status = "pending"
        self.github_comment_url = None
        self.created_at = datetime.now(timezone.utc)


class MarkdownFormatter:
    def format(self, r):
        return ("### CI Failure Triage\n\n"
                "**Category:** `%s`  **Confidence:** %.2f\n\n"
                "**Root cause**\n\n%s\n\n"
                "**Suggested fix**\n\n%s\n\n"
                "---\n"
                "<sub>Run `%s` · generated by Claude (%s). "
                "Verify before acting.</sub>\n"
                % (r.failure_category, r.confidence_score, r.root_cause,
                   r.suggested_fix, r.run_id, MODEL))


class GitHubClient:
    def __init__(self, token, repo):
        self.token, self.repo = token, repo

    def post_pr_comment(self, pr_number, body):
        url = "https://api.github.com/repos/%s/issues/%s/comments" % (
            self.repo, pr_number)
        req = urllib.request.Request(
            url, data=json.dumps({"body": body}).encode("utf-8"),
            headers={"Authorization": "Bearer " + self.token,
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28",
                     "Content-Type": "application/json",
                     "User-Agent": "ci-failure-triage-bot"},
            method="POST")
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8")).get("html_url")


# --------------------------------------------------------------------------
# TriageService.process_failed_run()
# --------------------------------------------------------------------------
def banner():
    print("")
    print(bold("  CI FAILURE TRIAGE BOT") + dim("  ·  end-to-end workflow"))
    print("")
    print("  " + dim("presentation │ ") + "1 webhook   2 verify   3 filter")
    print("  " + dim("application  │ ") + "4 fetch   5 trim   6 prompt   "
          + red("7 model") + "   8 validate")
    print("  " + dim("infrastructure│ ") + "9 format & post")
    print("")
    print("  " + dim("the only AI is step 7. the other eight are ordinary "
                     "engineering."))
    if _FOCUS:
        print("  " + dim("expanded in full: step " +
                         ", ".join(str(n) for n in sorted(_FOCUS))))
    print("")
    rule()


def run(args):
    t0 = time.time()
    kind = args.log
    repo = os.environ.get("GH_REPO", "nmcnpm-2026/demo-shop")
    pr = os.environ.get("GH_PR", "1")
    banner()

    # ---- 1 -------------------------------------------------------------
    with Step(1, "WebhookController", "handle_github_webhook",
              "GitHub POSTs here every time a workflow run finishes") as st:
        raw = {"_event": "workflow_run", "action": "completed",
               "repository": {"full_name": repo},
               "workflow_run": {"id": 8471023, "name": "ci",
                                "status": "completed", "conclusion": "failure",
                                "head_sha": "3f9c1ab7e42d0091",
                                "pull_requests": [{"number": int(pr)}]}}
        body = json.dumps(raw).encode("utf-8")
        p = WebhookPayload.from_dict(raw)
        if st.full:
            kv("in", "%s bytes of JSON on POST /webhook" % len(body))
            box("raw request body (truncated)",
                [blue(l) for l in json.dumps(raw, indent=2).split("\n")[:14]])
            kv("out", "WebhookPayload  " + dim("(a DTO, 8 fields)"))
            box("WebhookPayload", [
                "event       = %s" % blue(p.event),
                "status      = %s" % blue(p.status),
                "conclusion  = %s" % red(p.conclusion),
                "run_id      = %s" % p.run_id,
                "repo        = %s" % p.repo,
                "pr_number   = %s" % p.pr_number,
                "head_sha    = %s" % p.head_sha,
            ])
        st.done("%s · %s · run %s · PR #%s"
                % (blue(p.event), red(p.conclusion), p.run_id, p.pr_number))

    # ---- 2 -------------------------------------------------------------
    with Step(2, "SignatureVerifier", "verify",
              "anyone on the internet can POST here; without this, anyone "
              "could feed the model anything") as st:
        v = SignatureVerifier(WEBHOOK_SECRET)
        header = v.sign(body)                     # GitHub would send this
        ok = v.verify(body, header)
        if st.full:
            kv("in", "%d body bytes + the X-Hub-Signature-256 header" % len(body))
            box("HMAC-SHA256(secret, body)", [
                "received  " + yellow(header),
                "computed  " + yellow(v.sign(body)),
                "",
                "compare   " + (green("hmac.compare_digest → True")
                                if ok else red("mismatch → 401, stop")),
                dim("          constant-time compare, not ==, to avoid a "
                    "timing attack"),
            ])
            kv("out", green("accepted") if ok else red("rejected"))
        if not ok:
            st.done(red("HMAC mismatch — rejected"), ok=False)
            return 1
        st.done("HMAC-SHA256 " + green("ok") + dim("  " + header[:24] + "…"))

    # ---- 3 -------------------------------------------------------------
    with Step(3, "EventFilter", "is_valid_failure_event",
              "GitHub sends every run, including the green ones; we only "
              "pay for the red ones") as st:
        f = EventFilter()
        conds = f.conditions(p)
        if st.full:
            kv("in", "WebhookPayload")
            box("conditions", [
                "%s  %-12s expected %-14s got %s"
                % (green("✓") if exp == got else red("✗"), name,
                   blue(str(exp)), blue(str(got)))
                for name, exp, got in conds])
            kv("out", green("proceed") if f.is_valid_failure_event(p)
               else dim("drop, 204 No Content"))
        if not f.is_valid_failure_event(p):
            st.done("not a completed failure — ignored", ok=False)
            return 0
        st.done("3/3 conditions met  → " + green("proceed"))

    # ---- 4 -------------------------------------------------------------
    with Step(4, "GitHubClient", "get_workflow_logs",
              "download the job log over the REST API") as st:
        log_text = build_big_log(kind)
        lines = log_text.split("\n")
        kb = len(log_text.encode("utf-8")) / 1024.0
        if st.full:
            kv("in", "GET /repos/%s/actions/runs/%s/logs" % (repo, p.run_id))
            box("first 3 lines", [dim(l) for l in lines[:3]])
            box("last 3 lines", [red(l) for l in lines[-3:]])
            kv("out", "%s lines · %.0f KB · roughly %s tokens"
               % (bold("{:,}".format(len(lines))), kb,
                  yellow("{:,}".format(len(log_text) // 4))))
            kv("", red("far too large to send. that is the next step."))
        st.done("%s lines · %.0f KB" % (bold("{:,}".format(len(lines))), kb))

    # ---- 5 -------------------------------------------------------------
    with Step(5, "LogTrimmer", "trim",
              "input tokens cost money, and a model gets worse at finding "
              "one fact inside a huge context") as st:
        trimmed, total, kept, hits = LogTrimmer().trim(log_text)
        tl = trimmed.split("\n")
        if st.full:
            kv("in", "%s lines" % "{:,}".format(total))
            box("the rule", [
                "keep the last %s lines" % bold("40"),
                "plus every line matching %s error patterns" % bold("10"),
                "plus %s lines of context around each match" % bold("3"),
                "",
                dim("patterns: ##[error]  ^E   FAILED  Traceback  ERROR"),
                dim("          fatal:  Exception  SyntaxError  was canceled"),
                "",
                "%s pattern matches found in the log" % yellow(str(hits)),
            ])
            show = tl if len(tl) <= 26 else tl[:6] + [
                dim("        … %d more kept lines …" % (len(tl) - 26))] + tl[-20:]
            box("what actually gets sent to the model", [
                (red(l) if re.search(r"##\[error\]|^\s*E\s|FAILED|ERROR|SyntaxError", l)
                 else (dim(l) if "omitted" in l or "…" in l else l))
                for l in show], color=green)
            kv("out", "%s lines · %.1f KB · roughly %s tokens"
               % (bold(str(kept)), len(trimmed) / 1024.0,
                  green("{:,}".format(len(trimmed) // 4))))
            kv("", "%s of the log discarded — %s"
               % (yellow("%.1f%%" % (100.0 * (total - kept) / total)),
                  red("and this is the step most likely to throw away the answer")))
        st.done("%s → %s lines  (%s removed) · ~%s tokens"
                % ("{:,}".format(total), bold(str(kept)),
                   yellow("%.1f%%" % (100.0 * (total - kept) / total)),
                   len(trimmed) // 4))

    # ---- 6 -------------------------------------------------------------
    with Step(6, "PromptBuilder", "build",
              "assemble the message; the schema does NOT go in here — it "
              "goes in the tools field") as st:
        user_msg = PromptBuilder().build(trimmed, p)
        if st.full:
            kv("in", "trimmed log + WebhookPayload")
            head = user_msg.split("\n")[:8]
            box("user message (first 8 lines of %d)" % len(user_msg.split("\n")),
                head)
            kv("out", "%s characters" % "{:,}".format(len(user_msg)))
        st.done("system + user · %s chars · tool schema attached separately"
                % "{:,}".format(len(user_msg)))

    # ---- 7 -------------------------------------------------------------
    with Step(7, "ClaudeClient", "complete",
              "the only AI in the system. tool_choice forces a structured "
              "answer instead of prose") as st:
        usage, btype = None, "tool_use"
        if args.offline:
            if st.full:
                kv("in", dim("OFFLINE — no request sent"))
            time.sleep(0.5)
            data = CANNED[kind]
            st.done(yellow("OFFLINE") + " — using a saved response")
        else:
            try:
                cc = ClaudeClient()
                if st.full:
                    kv("in", "POST https://api.anthropic.com/v1/messages")
                    box("request shape",
                        [yellow(l) for l in json.dumps(cc.request_shape(user_msg),
                                                       indent=2).split("\n")])
                data, usage, btype = cc.complete(user_msg)
            except Exception as e:
                st.done(red(str(e)[:80]), ok=False)
                print("\n" + yellow("   falling back to the saved response\n"))
                data = CANNED[kind]
            else:
                if st.full:
                    box("response", [
                        "content[1].type  = " + green("'%s'" % btype),
                        "content[1].input = " + green("dict")
                        + dim("   ← already parsed. no extract_json() anywhere."),
                        "",
                        "usage.input_tokens  = %s" % yellow(str(usage.input_tokens)),
                        "usage.output_tokens = %s" % yellow(str(usage.output_tokens)),
                    ])
                    kv("out", "a Python dict with 4 keys")
                st.done("%s · %s in / %s out tokens"
                        % (green("tool_use"), usage.input_tokens,
                           usage.output_tokens))

    # ---- 8 -------------------------------------------------------------
    with Step(8, "ResponseValidator", "validate",
              "the schema guarantees shape, not meaning — the 600-char limit "
              "is only prose in a description") as st:
        rv = ResponseValidator()
        checks = rv.checks(data)
        if st.full:
            kv("in", "the dict from step 7")
            box("rules", ["%s  %-38s %s"
                          % (green("✓") if ok else red("✗"), name, dim(detail))
                          for name, ok, detail in checks])
            kv("out", green("valid") if all(o for _, o, _ in checks)
               else red("rejected"))
        bad = [n for n, o, _ in checks if not o]
        if bad:
            st.done(red("; ".join(bad)), ok=False)
            return 1
        st.done("%d/%d rules " % (len(checks), len(checks)) + green("passed"))

    result = TriageResult(p, data)
    comment = MarkdownFormatter().format(result)

    # ---- 9 -------------------------------------------------------------
    with Step(9, "MarkdownFormatter", "format + post",
              "render into a template and publish; this is the only side "
              "effect the bot can cause") as st:
        if args.post:
            token = os.environ.get("GH_TOKEN")
            if not token:
                st.done(red("GH_TOKEN is not set"), ok=False)
            else:
                try:
                    url = GitHubClient(token, repo).post_pr_comment(pr, comment)
                    result.comment_status, result.github_comment_url = "posted", url
                    if st.full:
                        kv("in", "POST /repos/%s/issues/%s/comments" % (repo, pr))
                        kv("out", green(url or "ok"))
                    st.done(green(url or "ok"))
                except Exception as e:
                    st.done(red(str(e)[:80]), ok=False)
        else:
            out = os.path.join(HERE, "comment.md")
            with open(out, "w", encoding="utf-8") as fh:
                fh.write(comment)
            result.comment_status = "rendered"
            if st.full:
                kv("in", "TriageResult + the comment template")
                kv("out", "demo/comment.md · %d characters" % len(comment))
                kv("", dim("the bot has one permission: post a comment. it "
                           "cannot merge, close, re-run or push."))
            st.done("demo/comment.md " + dim("(--post to publish to the PR)"))

    # ---- results ---------------------------------------------------------
    print("")
    rule("what the API returned  ·  already a dict, nothing to parse")
    print("")
    for line in json.dumps(data, indent=2, ensure_ascii=False).split("\n"):
        print("  " + (blue(line) if ":" in line else line))

    print("")
    rule("the comment on the pull request")
    print("")
    for line in comment.split("\n"):
        if line.startswith("###"):
            print("  " + bold(line.lstrip("# ")))
        elif line.startswith("**"):
            print("  " + red(line.replace("**", "")))
        elif line.startswith("<sub>") or line.startswith("---"):
            print("  " + dim(line.replace("<sub>", "").replace("</sub>", "")))
        else:
            print("  " + line)

    print("")
    rule()
    cost = ""
    if usage is not None:
        cost = dim("   ·   %s in / %s out tokens" % (usage.input_tokens,
                                                     usage.output_tokens))
    print("  " + green("9/9 steps") + dim("  ·  ")
          + "{:,}".format(total) + dim(" log lines in  →  ")
          + bold("1 comment") + dim(" out  ·  %.2fs" % (time.time() - t0)) + cost)
    print("")
    return 0


def parse_focus(s):
    if s.strip().lower() in ("none", ""):
        return set()
    if s.strip().lower() == "all":
        return set(range(1, 10))
    out = set()
    for part in s.split(","):
        part = part.strip()
        if part.isdigit() and 1 <= int(part) <= 9:
            out.add(int(part))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--focus", default="5,7",
                    help="steps to expand in full: '5,7' | 'all' | 'none'")
    ap.add_argument("--step", action="store_true",
                    help="wait for Enter between steps")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--post", action="store_true")
    ap.add_argument("--log", default="test",
                    choices=["test", "dependency", "syntax", "timeout"])
    ap.add_argument("--no-color", action="store_true")
    args = ap.parse_args()

    global _USE_COLOR, _FOCUS, _PAUSE
    _USE_COLOR = not args.no_color
    _FOCUS = parse_focus(args.focus)
    _PAUSE = args.step

    if not args.offline and not os.environ.get("ANTHROPIC_API_KEY"):
        print(yellow("\n  ANTHROPIC_API_KEY is not set — running offline.\n"))
        args.offline = True

    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
