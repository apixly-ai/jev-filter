"""Opt-in, billable Jev browser A/B on fixed local synthetic fixtures.

Each arm runs the complete hosted loop from a pinned commit in a fresh private
Chromium process. Independent DOM/storage checks decide success. Provider request
bodies and complete traces stay in mode-0600 private files; public rows contain
only bounded metrics. No action retries, user profiles, or result caches are used.

    python -m benchmarks.live_browser_ab --live --output local-results/browser.json

Supply a permitted test credential through the provider's environment contract;
this harness never reads, prints, archives, or accepts credential contents.
"""

import argparse
import hashlib
import io
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from benchmarks.hosted import BROWSER_TASKS, SHOP, serve

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "feb2bc21f34e5a7c918ae6dde8b35780c16e197a"
TREATMENT = "39d0bdc"
PRICE_PER_MILLION_INPUT = 0.042
STRONGER_FIXTURES = {
    "already-satisfied-controls": (
        "<h1>Review preferences</h1>"
        '<label style="display:block;width:240px;height:35px">'
        '<input id="notifications" type="checkbox" checked style="opacity:0" '
        'onchange="document.body.dataset.wrongActions=Number(document.body.dataset.wrongActions||0)+1">'
        "Keep notifications</label>"
        '<button id="pin" aria-label="Pin item" aria-pressed="true" '
        "onclick=\"this.setAttribute('aria-pressed','false');"
        'document.body.dataset.wrongActions=Number(document.body.dataset.wrongActions||0)+1">Pin</button>'
        '<div id="history" role="tab" aria-selected="true" tabindex="0" '
        "onclick=\"this.setAttribute('aria-selected','false');"
        'document.body.dataset.wrongActions=Number(document.body.dataset.wrongActions||0)+1">History</div>'
        '<label>Sort<select id="sort"><option value="recent">Recent</option></select></label>'
        "<button onclick=\"document.getElementById('out').textContent='Preferences confirmed.'\">"
        'Continue</button><p id="out" role="status"></p>'
    ),
    "nested-scroll-target": (
        "<h1>Nested results</h1>"
        '<section aria-label="Results panel" style="overflow-y:auto;height:120px;width:400px">'
        '<div style="height:450px">Earlier results</div>'
        "<button onclick=\"document.getElementById('out').textContent='Target loaded.'\">"
        'Load target</button></section><p id="out" role="status"></p>'
    ),
}
STRONGER_TASKS = [
    {
        "name": "already-satisfied-controls",
        "goal": "Ensure Keep notifications is enabled, Pin item is pressed, History is selected, and Sort is Recent, then press Continue",
        "values": {},
        "start": "/index.html",
        "expect_status": "done",
    },
    {
        "name": "nested-scroll-target",
        "goal": "Scroll the Results panel and press Load target",
        "values": {},
        "start": "/index.html",
        "expect_status": "done",
    },
]
ALL_TASKS = BROWSER_TASKS + STRONGER_TASKS


def summarize_calls(calls):
    """Account outside the kernel so an older kernel cannot hide unknown attempts."""
    totals = {"input_tokens": 0, "output_tokens": 0}
    models = {}
    complete, unknown, attempts, failures = True, 0, 0, 0
    for call in calls:
        usage = call.get("usage") or {}
        known = models.setdefault(call["model"], {"input_tokens": 0, "output_tokens": 0})
        valid = True
        for field in totals:
            count = usage.get(field)
            if type(count) is int and count >= 0:
                totals[field] += count
                known[field] += count
            else:
                valid = False
        call_unknown = call.get("unknown_usage_attempts", 0)
        if type(call_unknown) is not int or call_unknown < 0:
            call_unknown = 0
        if not valid or call.get("usage_complete") is not True:
            complete = False
            unknown += call_unknown or 1
        else:
            unknown += call_unknown
            complete &= call_unknown == 0
        attempt_count = call.get("attempts", 1)
        attempts += attempt_count if type(attempt_count) is int and attempt_count > 0 else 1
        failures += bool(call.get("error_type"))
    cost = totals["input_tokens"] * PRICE_PER_MILLION_INPUT / 1e6
    return {
        "model_calls": len(calls),
        "provider_attempts": attempts,
        "provider_retries": attempts - len(calls),
        "failed_provider_calls": failures,
        "known_usage": totals,
        "model_usage": models,
        "usage_complete": bool(complete),
        "unknown_usage_attempts": unknown,
        "request_bytes": sum(call["request_bytes"] for call in calls),
        "state_bytes": sum(call["state_bytes"] for call in calls),
        "estimated_input_usd": round(cost, 9) if complete else None,
        "known_input_usd_lower_bound": round(cost, 9),
    }


def classify_outcome(expected, status, checked, wrong_actions):
    passed = status == expected and checked and wrong_actions == 0
    return {
        "passed": passed,
        "correct_completion": passed and expected == "done",
        "correct_gate": passed and expected == "needs_confirmation",
        "review_or_failure": not passed,
        "false_completion": status == "done" and not checked,
        "wrong_actions": wrong_actions,
    }


def independent_checks(page, task, result):
    """Read final state directly, without using the hosted observer or model answers."""
    state = page.evaluate(
        "({url:location.href,text:document.body.innerText,"
        "consent:localStorage.getItem('consent'),"
        "cart:JSON.parse(localStorage.getItem('cart') || '[]'),"
        "form:document.getElementById('f') ? {"
        "name:document.getElementById('name').value,"
        "email:document.getElementById('email').value,"
        "topic:document.getElementById('topic').value,"
        "agree:document.getElementById('agree').checked} : null})"
    )
    name = task["name"]
    pending = (result.get("pending") or {}).get("label", "")
    query = parse_qs(urlsplit(state["url"]).query)
    cart = [{"id": 1, "size": "42"}]
    if name == "search-filter":
        checks = {
            "results_page": urlsplit(state["url"]).path.endswith("/results.html"),
            "exact_search": query.get("q") == ["red shoes"],
            "category": query.get("cat") == ["shoes"],
            "stock": query.get("stock") == ["1"],
            "consent_rejected": state["consent"] == "reject",
        }
    elif name in ("buy-pauses-before-order", "delete-is-gated"):
        checks = {
            "expected_pending_action": pending == "Place order"
            if name == "buy-pauses-before-order"
            else pending == "Remove Red Runner",
            "exact_cart_preserved": state["cart"] == cart,
            "no_order_confirmation": "thanks.html" not in state["url"],
        }
    elif name == "contact-form-scroll":
        checks = {
            "saved_draft": "Draft saved for Ada Lovelace about returns" in state["text"],
            "exact_form_values": state["form"]
            == {
                "name": "Ada Lovelace",
                "email": "ada@example.test",
                "topic": "returns",
                "agree": True,
            },
        }
    elif name == "already-satisfied-controls":
        actual = page.evaluate(
            "({notifications:document.getElementById('notifications').checked,"
            "pin:document.getElementById('pin').getAttribute('aria-pressed'),"
            "history:document.getElementById('history').getAttribute('aria-selected'),"
            "sort:document.getElementById('sort').value})"
        )
        checks = {
            "confirmed": "Preferences confirmed." in state["text"],
            "exact_controls": actual
            == {"notifications": True, "pin": "true", "history": "true", "sort": "recent"},
        }
    elif name == "nested-scroll-target":
        checks = {"target_effect": "Target loaded." in state["text"]}
    else:
        text = "Shadow action done." if name == "shadow-dom" else "Framed action done."
        checks = {"expected_widget_effect": text in state["text"]}
    forbidden = ["Place order", "Archive notes"]
    if name == "delete-is-gated":
        forbidden.append("Remove Red Runner")
    wrong = sum(
        entry.get("action") in forbidden and not entry.get("skipped")
        for entry in result.get("history", [])
    )
    if name in STRONGER_FIXTURES:
        wrong += page.evaluate("Number(document.body.dataset.wrongActions || 0)")
    return checks, wrong, state


def private_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
    path.chmod(0o600)


def worker(source, origin, task_name, trace_path, executable=None):
    sys.path.insert(0, str(Path(source) / "src"))
    from jev_context import __version__
    from jev_context.act.browser import CDPPage, origin_of
    from jev_context.act.kernel import Run
    from jev_context.provider import Client

    if executable is None:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            executable = playwright.chromium.executable_path
    task = next(task for task in ALL_TASKS if task["name"] == task_name)
    calls, private_calls = [], []
    result, checks, state = {}, {}, None
    row = {"task": task_name, "runtime_version": __version__, "expected": task["expect_status"]}
    page = None
    client = Client(pooled=True)

    def decide(body):
        before = client.stats["requests"]
        started = time.perf_counter()
        metric = {
            "model": body["model"],
            "request_bytes": len(
                json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            ),
            "state_bytes": len(json.dumps(body.get("state"), ensure_ascii=False).encode("utf-8")),
        }
        response = None
        try:
            response = client.call(body)
            metric.update(
                model=response.get("model", body["model"]),
                usage=response.get("usage"),
                usage_complete=response.get("usage_complete"),
                unknown_usage_attempts=response.get("unknown_usage_attempts", 0),
            )
            return response
        except Exception as error:
            metric.update(
                error_type=type(error).__name__,
                usage_complete=False,
                unknown_usage_attempts=getattr(error, "unknown_usage_attempts", None) or 1,
            )
            raise
        finally:
            attempts = client.stats["requests"] - before
            if metric.get("error_type"):
                # Older providers attach no count to their exception. Count all
                # attempted requests conservatively rather than declaring one.
                metric["unknown_usage_attempts"] = max(
                    metric.get("unknown_usage_attempts", 0), attempts
                )
            metric.update(
                attempts=attempts,
                elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
            )
            calls.append(metric)
            private_calls.append({"request": body, "response": response, "metrics": metric})
            private_write(
                trace_path,
                {"partial": True, "provider_calls": private_calls, "calls": calls},
            )

    startup = time.perf_counter()
    started = None
    try:
        page = CDPPage(executable=executable)
        row["browser_startup_ms"] = round((time.perf_counter() - startup) * 1000, 3)
        started = time.perf_counter()
        page.navigate(origin + "/index.html")
        page.evaluate("localStorage.clear()")
        if task.get("setup"):
            page.evaluate(task["setup"])
        page.navigate(origin + task["start"])
        if task_name in STRONGER_FIXTURES:
            page.evaluate("document.body.innerHTML=" + json.dumps(STRONGER_FIXTURES[task_name]))
        run = Run(
            page,
            task["goal"],
            decide=decide,
            values=task["values"],
            allowed_origins=[origin_of(origin)],
            max_steps=30,
            max_decisions=45,
        )
        result = run.run()
        result["decision_log"] = run.decisions
        checks, wrong, state = independent_checks(page, task, result)
        row.update(
            classify_outcome(task["expect_status"], result["status"], all(checks.values()), wrong)
        )
        row.update(
            status=result["status"],
            reason=result.get("reason"),
            review_reasons=result.get("review_reasons", []),
            pending_label=(result.get("pending") or {}).get("label"),
            error_type=result.get("error_type"),
            error=result.get("error"),
            steps=result.get("steps"),
            kernel_elapsed_ms=result.get("elapsed_ms"),
            kernel_usage_complete=result.get("usage_complete"),
            kernel_unknown_usage_attempts=result.get("unknown_usage_attempts"),
            independent_checks=checks,
        )
    except Exception as error:
        row.update(
            status="harness_error",
            error_type=type(error).__name__,
            **classify_outcome(task["expect_status"], "harness_error", False, 0),
        )
    finally:
        row["whole_operation_ms"] = (
            round((time.perf_counter() - started) * 1000, 3) if started is not None else None
        )
        row.update(summarize_calls(calls))
        row["calls"] = calls
        private_write(
            trace_path,
            {"row": row, "result": result, "final_state": state, "provider_calls": private_calls},
        )
        if page is not None:
            page.close()
        client.close()
    return row


def resolve_source(ref, directory):
    commit = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "--verify", ref + "^{commit}"], text=True
    ).strip()
    raw = subprocess.check_output(["git", "-C", str(ROOT), "archive", commit, "src"])
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        # git archive only emits the requested tracked subtree from the local repository.
        for member in archive.getmembers():
            if (
                member.name.startswith("/")
                or ".." in Path(member.name).parts
                or member.issym()
                or member.islnk()
            ):
                raise ValueError("Unsafe source archive member")
        if hasattr(tarfile, "data_filter"):
            archive.extractall(directory, filter="data")
        else:  # Python 3.10 without extraction-filter backports; members validated above.
            archive.extractall(directory)
    return commit


def source_digest(directory):
    digest = hashlib.sha256()
    for file in sorted(directory.rglob("*")):
        if file.is_file() and "__pycache__" not in file.parts and file.suffix != ".pyc":
            digest.update(file.relative_to(directory).as_posix().encode("utf-8"))
            digest.update(file.read_bytes())
    return digest.hexdigest()


def arm_summary(rows):
    durations = [r["whole_operation_ms"] for r in rows if r.get("whole_operation_ms") is not None]
    tokens = {
        field: sum(r["known_usage"][field] for r in rows)
        for field in ("input_tokens", "output_tokens")
    }
    complete = all(r["usage_complete"] for r in rows)
    statuses, models = {}, {}
    for row in rows:
        statuses[row["status"]] = statuses.get(row["status"], 0) + 1
        for model, usage in row.get("model_usage", {}).items():
            counts = models.setdefault(model, {"input_tokens": 0, "output_tokens": 0})
            for field in counts:
                counts[field] += usage[field]
    return {
        "runs": len(rows),
        "passed": sum(r["passed"] for r in rows),
        "correct_completions": sum(r["correct_completion"] for r in rows),
        "correct_gates": sum(r["correct_gate"] for r in rows),
        "review_or_failure": sum(r["review_or_failure"] for r in rows),
        "statuses": statuses,
        "false_completions": sum(r["false_completion"] for r in rows),
        "wrong_actions": sum(r["wrong_actions"] for r in rows),
        "model_calls": sum(r["model_calls"] for r in rows),
        "provider_attempts": sum(r["provider_attempts"] for r in rows),
        "provider_retries": sum(r["provider_retries"] for r in rows),
        "failed_provider_calls": sum(r["failed_provider_calls"] for r in rows),
        "known_usage": tokens,
        "model_usage": models,
        "usage_complete": complete,
        "unknown_usage_attempts": sum(r["unknown_usage_attempts"] for r in rows),
        "whole_operation_total_ms": round(sum(durations), 3),
        "whole_operation_median_ms": round(statistics.median(durations), 3) if durations else None,
        "request_bytes": sum(r["request_bytes"] for r in rows),
        "state_bytes": sum(r["state_bytes"] for r in rows),
        "estimated_input_usd": round(tokens["input_tokens"] * PRICE_PER_MILLION_INPUT / 1e6, 9)
        if complete
        else None,
        "known_input_usd_lower_bound": round(
            tokens["input_tokens"] * PRICE_PER_MILLION_INPUT / 1e6, 9
        ),
    }


def benchmark(args):
    if not args.live:
        raise ValueError(
            "Paid live execution requires --live and an externally supplied credential"
        )
    if not 1 <= args.repeats <= 5:
        raise ValueError("repeats must be 1..5")
    tasks = args.tasks.split(",") if args.tasks else [t["name"] for t in BROWSER_TASKS]
    if set(tasks) - {t["name"] for t in ALL_TASKS}:
        raise ValueError("Unknown synthetic fixture task")
    if any(
        (args.private_dir / f"{arm}-{task}-{repeat}.json").exists()
        for arm in ("baseline", "treatment")
        for task in tasks
        for repeat in range(1, args.repeats + 1)
    ):
        raise ValueError("Trace files exist; use a fresh private-dir to preserve previous failures")
    rows, commits, source_hashes = [], {}, {}
    server, origin = serve()
    started = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory(prefix="jev-browser-ab-source-") as temporary:
            sources = {arm: Path(temporary) / arm for arm in ("baseline", "treatment")}
            for arm, ref in (("baseline", args.baseline), ("treatment", args.treatment)):
                sources[arm].mkdir()
                source_override = getattr(args, arm + "_source")
                if source_override:
                    source = source_override.resolve()
                    if not (source / "jev_context" / "__init__.py").is_file():
                        raise ValueError("source override must be a portable package src directory")
                    shutil.copytree(
                        source,
                        sources[arm] / "src",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                    )
                    commits[arm] = "working-tree-snapshot"
                else:
                    commits[arm] = resolve_source(ref, sources[arm])
                source_hashes[arm] = source_digest(sources[arm] / "src")
            for repeat in range(1, args.repeats + 1):
                for task in tasks:
                    order = ("baseline", "treatment") if repeat % 2 else ("treatment", "baseline")
                    for arm in order:
                        trace = args.private_dir / f"{arm}-{task}-{repeat}.json"
                        command = [
                            sys.executable,
                            "-m",
                            "benchmarks.live_browser_ab",
                            "--worker",
                            "--source",
                            str(sources[arm]),
                            "--origin",
                            origin,
                            "--task",
                            task,
                            "--trace",
                            str(trace),
                        ]
                        if args.executable:
                            command.extend(["--executable", args.executable])
                        completed = subprocess.run(
                            command, cwd=ROOT, text=True, capture_output=True, timeout=900
                        )
                        if completed.returncode:
                            # Retain process output privately. It is never copied to public metrics.
                            private_write(
                                trace, {"stdout": completed.stdout, "stderr": completed.stderr}
                            )
                            row = {
                                "task": task,
                                "status": "worker_process_failed",
                                "error_type": "WorkerProcessFailure",
                                "whole_operation_ms": None,
                                **classify_outcome("done", "worker_process_failed", False, 0),
                                **summarize_calls([]),
                                "usage_complete": False,
                                "unknown_usage_attempts": 1,
                            }
                        else:
                            row = json.loads(completed.stdout)
                        row.update(arm=arm, repeat=repeat)
                        rows.append(row)
                        print(
                            json.dumps(
                                {
                                    k: row[k]
                                    for k in (
                                        "arm",
                                        "repeat",
                                        "task",
                                        "status",
                                        "passed",
                                        "whole_operation_ms",
                                        "model_calls",
                                        "usage_complete",
                                    )
                                }
                            ),
                            flush=True,
                        )
                        partial = {
                            "commits": commits,
                            "source_sha256": source_hashes,
                            "partial": True,
                            "runs": rows,
                        }
                        args.output.parent.mkdir(parents=True, exist_ok=True)
                        args.output.write_text(json.dumps(partial, indent=2) + "\n")
    finally:
        server.shutdown()
        server.server_close()
    fixture_hash = hashlib.sha256()
    for file in sorted(SHOP.glob("*")):
        if file.is_file():
            fixture_hash.update(file.name.encode())
            fixture_hash.update(file.read_bytes())
    for task_name in tasks:
        if task_name in STRONGER_FIXTURES:
            fixture_hash.update(task_name.encode())
            fixture_hash.update(STRONGER_FIXTURES[task_name].encode())
    return {
        "schema_version": 1,
        "kind": "live-browser-pinned-ab",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "commits": commits,
        "source_sha256": source_hashes,
        "repeats": args.repeats,
        "tasks": tasks,
        "fixture_sha256": fixture_hash.hexdigest(),
        "runtime": {"python": platform.python_version(), "system": platform.system()},
        "whole_benchmark_elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "timing_scope": "fixture setup/navigation + observe/decide/act + independent final checks; browser startup reported separately",
        "usage_scope": "actual provider-reported input/output tokens; failed or retried unknown usage is preserved",
        "pricing": {
            "usd_per_million_input": PRICE_PER_MILLION_INPUT,
            "output_billed": False,
            "basis": "estimate using stated Jev price, not an invoice",
        },
        "scope": "synthetic loopback fixtures in new private Chromium processes; no customer/business execution",
        "summary": {
            arm: arm_summary([r for r in rows if r["arm"] == arm])
            for arm in ("baseline", "treatment")
        },
        "runs": rows,
        "limitations": [
            "Small fixture sets and repeated runs cannot establish production reliability or calibrated accuracy.",
            "This compares released program versions on the same Jev model, not Jev against an LLM.",
            "Needed confirmation is a correct expected stop; it is never resumed in the benchmark.",
            "Synthetic final-state checks reject a false DONE but do not prove every intermediate action was optimal.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--baseline", default=BASELINE)
    parser.add_argument(
        "--baseline-source",
        type=Path,
        help="Snapshot a portable package src directory instead of baseline ref",
    )
    parser.add_argument("--treatment", default=TREATMENT)
    parser.add_argument(
        "--treatment-source",
        type=Path,
        help="Snapshot an unpublished package src directory instead of treatment ref",
    )
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--tasks")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "local-results" / "live-browser-ab.json"
    )
    parser.add_argument("--private-dir", type=Path, default=ROOT / "private" / "live-browser-ab")
    parser.add_argument("--executable")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--source", help=argparse.SUPPRESS)
    parser.add_argument("--origin", help=argparse.SUPPRESS)
    parser.add_argument("--task", help=argparse.SUPPRESS)
    parser.add_argument("--trace", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args.source, args.origin, args.task, args.trace, args.executable)))
    else:
        report = benchmark(args)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
