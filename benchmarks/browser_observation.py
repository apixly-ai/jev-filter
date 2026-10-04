"""Local Chromium observation/action A/B against an explicitly pinned old page script.

No inference occurs: a fixed program selects only actions the observer enumerates, and
independent DOM checks verify the result. Timings include fixture navigation, observation,
action and checks, excluding browser startup. This is not a Jev planning-quality benchmark.
"""

import argparse
import hashlib
import json
import platform
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from jev_context import __version__
from jev_context.act import space
from jev_context.act.browser import PAGE_JS, CDPPage, StalePage
from jev_context.command import collect_command
from jev_context.diff import _commit

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = "feb2bc21f34e5a7c918ae6dde8b35780c16e197a"
FIXTURES = {
    "typed_states": (
        '<label><input type="checkbox">Notifications</label>'
        '<button aria-label="Pin item" aria-pressed="false">Pin</button>'
        '<div role="tab" aria-selected="false">History</div>'
        '<label>Sort<select><option value="recent">Recent</option></select></label>'
        '<input aria-label="Note" value="">'
    ),
    "roleless_click": (
        '<div tabindex="0" style="cursor:pointer;width:220px;height:40px" '
        "onclick=\"document.body.dataset.result='opened'\">Open details</div>"
        '<div style="width:220px;height:40px">Static text</div>'
    ),
    "transparent_toggle": (
        '<label style="display:block;width:220px;height:40px">'
        '<input type="checkbox" style="opacity:0;width:15px;height:15px">Styled toggle</label>'
        '<label><input disabled type="checkbox" style="opacity:0">Disabled toggle</label>'
    ),
    "nested_scroll": (
        '<section aria-label="Results panel" style="overflow-y:auto;height:120px;width:400px">'
        '<div style="height:500px">Earlier results</div>'
        "<button onclick=\"document.body.dataset.result='opened'\">Load target</button></section>"
    ),
    "freshness_occlusion": (
        '<button id="target" onclick="document.body.dataset.result=\'wrong\'">Inspect result</button>'
        "<button disabled>Disabled action</button>"
    ),
}


class FixturePage(CDPPage):
    def call(self, request, await_promise=False):
        expression = "(" + self.page_source + ")(" + json.dumps(request) + ")"
        return self.evaluate(expression, await_promise=await_promise)


def executable_path():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        path = playwright.chromium.executable_path
    if not Path(path).is_file():
        raise RuntimeError("Install the optional Playwright Chromium before this local benchmark")
    return path


def _find(state, label, kind=None):
    return next(
        (
            a
            for a in state["actions"]
            if a["label"] == label and (kind is None or a["kind"] == kind)
        ),
        None,
    )


def measure_case(page, case):
    started = time.perf_counter()
    page.navigate("about:blank")
    page.evaluate("document.body.innerHTML=" + json.dumps(FIXTURES[case]))
    contexts, observed, executed = [], 0, 0

    def observe():
        nonlocal observed
        observed += 1
        state = page.observe()
        request, _, _ = space.build_request(state, "Synthetic local fixture check", [])
        contexts.append(space.request_bytes(request))
        return state

    state = observe()
    probes = []
    missing, freshness = 0, []
    passed = False
    if case == "typed_states":
        expected = [
            ("Notifications", "checked", False),
            ("Pin item", "pressed", False),
            ("History", "selected", False),
            ("Sort", "control_value", "recent"),
            ("Note", "value", ""),
        ]
        for label, field, value in expected:
            action = _find(state, label)
            present = action is not None and field in action
            actual = action.get(field) if present else None
            match = present and type(actual) is type(value) and actual == value
            probes.append(
                {
                    "label": label,
                    "field": field,
                    "expected": value,
                    "actual": actual,
                    "match": match,
                }
            )
        missing = sum(not probe["match"] for probe in probes)
        passed = not missing
    elif case == "roleless_click":
        action = _find(state, "Open details")
        missing = int(action is None)
        if action:
            page.act(action, state)
            executed += 1
        passed = page.evaluate("document.body.dataset.result") == "opened"
        probes.append({"noninteractive_excluded": _find(state, "Static text") is None})
        passed = passed and probes[-1]["noninteractive_excluded"]
    elif case == "transparent_toggle":
        action = _find(state, "Styled toggle")
        missing = int(action is None)
        if action:
            page.act(action, state)
            executed += 1
        passed = page.evaluate("document.querySelector('input').checked") is True
        probes.append({"disabled_excluded": _find(state, "Disabled toggle") is None})
        passed = passed and probes[-1]["disabled_excluded"]
    elif case == "nested_scroll":
        for _ in range(8):
            target = _find(state, "Load target")
            if target:
                page.act(target, state)
                executed += 1
                break
            scroll = next(
                (
                    a
                    for a in state["actions"]
                    if a["kind"] == "scroll" and a.get("node") and a["delta"] > 0
                ),
                None,
            )
            if scroll is None:
                missing = 1
                break
            page.act(scroll, state)
            executed += 1
            state = observe()
        passed = page.evaluate("document.body.dataset.result") == "opened"
    else:
        action = _find(state, "Inspect result")
        page.evaluate("document.getElementById('target').textContent='Changed result'")
        try:
            page.act(action, state)
            freshness.append(False)
        except StalePage:
            freshness.append(True)
        state = observe()
        action = _find(state, "Changed result")
        page.evaluate(
            "(() => { const cover = document.createElement('div');"
            "cover.style.cssText='position:fixed;inset:0;z-index:10;background:transparent';"
            "document.body.appendChild(cover); })()"
        )
        try:
            page.resolve(action)
            freshness.append(False)
        except StalePage:
            freshness.append(True)
        probes.append({"disabled_excluded": _find(state, "Disabled action") is None})
        passed = all(freshness) and probes[-1]["disabled_excluded"]
    wrong_actions = int(page.evaluate("document.body.dataset.result") == "wrong")
    return {
        "passed": passed,
        "probes": probes,
        "typed_state_recall": (sum(p["match"] for p in probes) / len(probes))
        if case == "typed_states"
        else None,
        "missing_or_mismatched_controls": missing,
        "wrong_actions": wrong_actions,
        "freshness_rejections": sum(freshness),
        "freshness_checks": len(freshness),
        "observations": observed,
        "executed_observed_actions": executed,
        "whole_operation_ms": round((time.perf_counter() - started) * 1000, 3),
        "planned_context_bytes": sum(contexts),
        "context_samples_bytes": contexts,
        "model_usage": [],
        "model_requests": 0,
        "inference_cost_usd": 0,
    }


def run(baseline_ref=DEFAULT_BASELINE, repeats=3, executable=None):
    if not 1 <= repeats <= 10:
        raise ValueError("repeats must be 1..10")
    commit = _commit(ROOT, baseline_ref)
    rows, meta = collect_command(
        ["git", "-C", str(ROOT), "show", commit + ":src/jev_context/act/page.js"], split="whole"
    )
    if not meta["ok"]:
        raise ValueError("Baseline commit must contain src/jev_context/act/page.js")
    baseline = rows[0]["text"]
    rows = []
    page = FixturePage(executable=executable or executable_path())
    try:
        for repeat in range(repeats):
            for case in FIXTURES:
                order = ("baseline", "treatment") if repeat % 2 == 0 else ("treatment", "baseline")
                for arm in order:
                    page.page_source = baseline if arm == "baseline" else PAGE_JS
                    result = measure_case(page, case)
                    rows.append({"case": case, "arm": arm, "repeat": repeat, **result})
    finally:
        page.close()
    summary = {}
    for arm in ("baseline", "treatment"):
        selected = [r for r in rows if r["arm"] == arm]
        summary[arm] = {
            "passed_cases": sum(r["passed"] for r in selected),
            "cases": len(selected),
            "typed_state_recall": statistics.mean(
                r["typed_state_recall"] for r in selected if r["typed_state_recall"] is not None
            ),
            "wrong_actions": sum(r["wrong_actions"] for r in selected),
            "freshness_rejections": sum(r["freshness_rejections"] for r in selected),
            "freshness_checks": sum(r["freshness_checks"] for r in selected),
            "median_whole_operation_ms": statistics.median(
                r["whole_operation_ms"] for r in selected
            ),
            "mean_planned_context_bytes": statistics.mean(
                r["planned_context_bytes"] for r in selected
            ),
        }
    return {
        "schema_version": 1,
        "kind": "offline_local_browser_observation_action_ab",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "version": __version__,
        "python": platform.python_version(),
        "platform": platform.system(),
        "baseline_commit": commit,
        "baseline_page_js_sha256": hashlib.sha256(baseline.encode()).hexdigest(),
        "treatment_page_js_sha256": hashlib.sha256(PAGE_JS.encode()).hexdigest(),
        "fixture_sha256": hashlib.sha256(json.dumps(FIXTURES, sort_keys=True).encode()).hexdigest(),
        "result_cache": False,
        "model_usage": [],
        "scope": "Pinned old and current DOM observer with identical current CDP transport, fixed program-owned action policy, synthetic about:blank HTML; no Jev inference or external accounts.",
        "cost_assumption": "No inference requests: zero model tokens and inference cost, not a hosted end-to-end model cost estimate.",
        "timing_boundary": "Fixture navigation plus injection, observation, action and independent DOM checks; browser startup excluded.",
        "limitations": [
            "Typed-state probe requires boolean ARIA/native states and exact current SELECT value; it is an observation contract check, not model accuracy.",
            "More observed controls and successful multi-step scrolling increase context and runtime; medians combine different task completion paths.",
            "Roleless controls require explicit onclick or focusable pointer styling; transparent inputs supported only for labelled native checkbox/radio toggles.",
            "Nested scrolling is vertical; new-tab switching, closed shadow roots and cross-origin frames remain outside scope.",
        ],
        "summary": summary,
        "runs": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", default=DEFAULT_BASELINE)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--executable")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = run(args.baseline_ref, args.repeats, args.executable)
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"kind": result["kind"], "summary": result["summary"]}))
    return 0 if all(r["passed"] for r in result["runs"] if r["arm"] == "treatment") else 2


if __name__ == "__main__":
    raise SystemExit(main())
