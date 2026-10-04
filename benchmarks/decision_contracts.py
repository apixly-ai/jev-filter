"""Reproduce core reliability/uncertainty A/B on fixed scripted synthetic decisions.

Baseline source is read from a pinned local Git commit. No models, credentials, real browser,
customer records or result caches are used. Timing measures complete simulated operations.
"""

import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

BASELINE = "feb2bc21f34e5a7c918ae6dde8b35780c16e197a"
UNCERTAINTY = {"min_top_probability": 0.55, "min_margin": 0.10}


def _choice(choice, distribution):
    ranked = sorted(distribution.values(), reverse=True)
    return {
        "type": "choice",
        "choice": choice,
        "probabilities": distribution,
        "confidence": ranked[0] - (ranked[1] if len(ranked) > 1 else 0),
    }


def _worker(label):
    from unittest.mock import patch

    from jev_context import analysis
    from jev_context.act import kernel
    from jev_context.provider import ProviderError

    treatment = label == "treatment"
    rows = []
    parts = [{"id": "p0", "source_id": "s0", "text": "Synthetic record", "source": {}}]

    def analysis_case(name, probabilities, chosen, expected, requirements=False, choose=False):
        spec = {"mode": "choose"} if choose else {}
        if requirements:
            spec["requirements"] = [{"id": "current", "statement": "Is current", "expected": True}]
        if treatment:
            spec["uncertainty"] = UNCERTAINTY
        spec = analysis.validate(spec)
        answer = _choice(chosen, probabilities)
        planned = analysis.plan(parts, "Evaluate the synthetic evidence", spec)
        key = "target" if choose else "p0q0"
        response = {
            "ok": True,
            "usage_complete": True,
            "usage": {"input_tokens": 100, "output_tokens": 10},
            "results": [{"id": "choose" if choose else "0", "ok": True, "answers": {key: answer}}],
        }
        started = time.perf_counter_ns()
        with patch("jev_context.pool.run", return_value=response):
            judgments, telemetry = analysis.evaluate(
                parts, "Evaluate the synthetic evidence", spec=spec
            )
            output = analysis.summarize(parts, judgments, spec)
            decision = analysis.decision(judgments["p0"], spec, parts[0])
        elapsed = time.perf_counter_ns() - started
        rows.append(
            {
                "id": name,
                "expected": expected,
                "actual": decision,
                "correct": decision == expected,
                "false_actions": 0,
                "review": decision == "REVIEW",
                "unsafe_automatic": expected == "REVIEW" and decision != "REVIEW",
                "operation_elapsed_ns": elapsed,
                "request_context_bytes": sum(
                    analysis.encoded_bytes(i["request"]) for i in planned["items"]
                ),
                "returned_context_bytes": analysis.encoded_bytes(output),
                "simulated_usage": telemetry.get("usage"),
            }
        )

    analysis_case(
        "requirement_clear",
        {"SUPPORTED": 0.99, "CONTRADICTED": 0.005, "UNKNOWN": 0.005},
        "SUPPORTED",
        "MATCH",
        True,
    )
    analysis_case(
        "requirement_weak",
        {"SUPPORTED": 0.36, "CONTRADICTED": 0.33, "UNKNOWN": 0.31},
        "SUPPORTED",
        "REVIEW",
        True,
    )
    analysis_case(
        "filter_clear_negative",
        {"OTHER": 0.99, "RELEVANT": 0.005, "REVIEW": 0.005},
        "OTHER",
        "EXCLUDE",
    )
    analysis_case(
        "filter_weak_negative", {"OTHER": 0.51, "RELEVANT": 0.49, "REVIEW": 0}, "OTHER", "REVIEW"
    )
    analysis_case(
        "choose_weak", {"c0": 0.51, "NONE": 0.49, "REVIEW": 0}, "c0", "REVIEW", choose=True
    )

    class Surface:
        def __init__(self, fill=False):
            self.current = {
                "url": "https://fixture.test/",
                "title": "Fixture",
                "text": "Synthetic controls",
                "fingerprint": "initial",
                "actions": [
                    {
                        "id": "a",
                        "kind": "fill" if fill else "click",
                        "node": 1,
                        "label": "Search",
                        "role": "textbox" if fill else "button",
                    },
                    {"id": "b", "kind": "click", "node": 2, "label": "Browse", "role": "button"},
                ],
            }
            self.executed = []

        def observe(self, **kwargs):
            return self.current

        def fresh(self, page, action=None):
            return page["fingerprint"] == self.current["fingerprint"]

        def act(self, action, page, text=None):
            self.executed.append(action["id"])
            self.current = {**self.current, "fingerprint": "finished", "text": "Finished"}
            return {"executed": action["id"]}

        def settle(self, action):
            pass

    def hosted_case(name, kind, expected, expected_actions=0):
        surface = Surface(fill=kind in ("value", "helper_failure"))
        bodies = []

        def decide(body):
            bodies.append(body)
            if kind == "first_failure" or kind == "later_failure" and len(bodies) > 1:
                raise ProviderError("transport_failed_usage_unknown")
            if "verified" in body["questions"]:
                raise ProviderError("response_invalid_usage_unknown")
            operation = (
                "DONE"
                if surface.executed or kind == "verifier_failure"
                else ("TYPE_TEXT" if kind in ("value", "helper_failure") else "CLICK")
            )
            answers = {}
            for key, question in body["questions"].items():
                if question["type"] == "noul":
                    answers[key] = {"type": "noul", "noul": 0}
                else:
                    selected = operation if key == "operation" else next(iter(question["criteria"]))
                    answers[key] = _choice(
                        selected,
                        {option: float(option == selected) for option in question["criteria"]},
                    )
            if not surface.executed and kind == "target":
                answers["click_target"] = _choice("1", {"1": 0.51, "2": 0.49})
            if not surface.executed and kind == "weak_operation":
                probs = {key: 0.0 for key in answers["operation"]["probabilities"]}
                probs.update(BLOCKED=0.45, CLICK=0.35, TYPE_TEXT=0)
                # The fixture has no WAIT control: the remainder belongs to DONE.
                probs.pop("TYPE_TEXT")
                probs["DONE"] = 0.20
                answers["operation"] = _choice("BLOCKED", probs)
            if not surface.executed and kind == "value":
                answers["type_value"] = _choice("query", {"query": 0.51, "NONE": 0.49})
            return {
                "answers": answers,
                "usage": {"input_tokens": 100, "output_tokens": 10},
                "usage_complete": True,
            }

        kwargs = {}
        if kind == "value":
            kwargs["values"] = {"query": "red shoes"}
        if kind == "verifier_failure":
            kwargs["verify_question"] = "Did the synthetic operation finish?"
        if kind == "helper_failure":
            from jev_context.act.text import TextHelperError

            def failed_helper(context):
                raise TextHelperError("text_model_unreachable")

            kwargs["text_helper"] = failed_helper
        started = time.perf_counter_ns()
        try:
            output = kernel.Run(
                surface, "Search the synthetic fixture", decide=decide, **kwargs
            ).run()
            actual = output["status"]
        except Exception as error:
            output = {"status": "raised", "error_type": type(error).__name__}
            actual = "raised"
        elapsed = time.perf_counter_ns() - started
        safe = {
            key: output.get(key)
            for key in (
                "usage",
                "usage_complete",
                "unknown_usage_attempts",
                "error",
                "error_type",
                "verification",
                "text_model_usage",
            )
            if key in output
        }
        bookkeeping_preserved = True
        if kind in ("first_failure", "later_failure", "verifier_failure"):
            bookkeeping_preserved = (
                output.get("usage_complete") is False and output.get("unknown_usage_attempts") == 1
            )
            if kind == "verifier_failure":
                bookkeeping_preserved = (
                    bookkeeping_preserved
                    and (output.get("verification") or {}).get("question_error")
                    == "response_invalid_usage_unknown"
                )
            else:
                bookkeeping_preserved = (
                    bookkeeping_preserved
                    and output.get("error") == "transport_failed_usage_unknown"
                )
            if kind == "later_failure":
                bookkeeping_preserved = bookkeeping_preserved and output.get("usage") == {
                    "input_tokens": 100,
                    "output_tokens": 10,
                }
        elif kind == "helper_failure":
            bookkeeping_preserved = (
                output.get("error") == "text_model_unreachable"
                and (output.get("text_model_usage") or {}).get("usage_complete") is False
                and (output.get("text_model_usage") or {}).get("unknown_usage_attempts") == 1
            )
        rows.append(
            {
                "id": name,
                "expected": expected,
                "actual": actual,
                "correct": actual == expected and bookkeeping_preserved,
                "bookkeeping_preserved": bookkeeping_preserved,
                "expected_actions": expected_actions,
                "executed_actions": len(surface.executed),
                "false_actions": max(0, len(surface.executed) - expected_actions),
                "review": actual == "needs_review",
                "unsafe_automatic": expected == "needs_review" and bool(surface.executed),
                "operation_elapsed_ns": elapsed,
                "request_context_bytes": sum(analysis.encoded_bytes(body) for body in bodies),
                "returned_context_bytes": analysis.encoded_bytes(output),
                "bookkeeping": safe,
            }
        )

    hosted_case("hosted_clear_target", "clear", "done", 1)
    hosted_case("hosted_weak_target", "target", "needs_review")
    hosted_case("hosted_weak_value", "value", "needs_review")
    hosted_case("hosted_weak_operation", "weak_operation", "needs_review")
    hosted_case("first_provider_failure", "first_failure", "error")
    hosted_case("provider_failure_after_success", "later_failure", "error", 1)
    hosted_case("verifier_failure", "verifier_failure", "unverified")
    hosted_case("text_helper_failure", "helper_failure", "error")
    return {
        "label": label,
        "cases": rows,
        "correct": sum(r["correct"] for r in rows),
        "case_count": len(rows),
        "unsafe_automatic_decisions": sum(r["unsafe_automatic"] for r in rows),
        "false_actions": sum(r["false_actions"] for r in rows),
        "reviews": sum(r["review"] for r in rows),
        "operation_elapsed_ns": sum(r["operation_elapsed_ns"] for r in rows),
        "request_context_bytes": sum(r["request_context_bytes"] for r in rows),
        "returned_context_bytes": sum(r["returned_context_bytes"] for r in rows),
        "actual_model_usage": {
            "requests": 0,
            "models": {},
            "input_tokens": 0,
            "output_tokens": 0,
            "usage_complete": True,
        },
    }


def run(baseline=BASELINE):
    started = time.perf_counter_ns()
    root = Path(__file__).resolve().parents[1]
    baseline_sha = subprocess.check_output(
        ["git", "rev-parse", "--verify", baseline + "^{commit}"], cwd=root, text=True
    ).strip()
    archive = subprocess.check_output(
        ["git", "archive", "--format=tar", baseline_sha, "src"], cwd=root
    )
    with tempfile.TemporaryDirectory(prefix="jev-core-baseline-") as directory:
        directory = Path(directory)
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            for member in bundle:
                path = Path(member.name)
                if member.isfile() and path.parts[0] == "src" and ".." not in path.parts:
                    target = directory / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(bundle.extractfile(member).read())
        rows = []
        for label, source in (("baseline", directory / "src"), ("treatment", root / "src")):
            env = {**os.environ, "PYTHONPATH": str(source), "PYTHONDONTWRITEBYTECODE": "1"}
            command = [sys.executable, str(Path(__file__).resolve()), "--worker", label]
            output = subprocess.check_output(command, cwd=directory, env=env, text=True)
            rows.append(json.loads(output))
    return {
        "benchmark": "synthetic_core_decision_contracts",
        "version": 1,
        "baseline_commit": baseline_sha,
        "treatment_base_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip(),
        "treatment_source_sha256": hashlib.sha256(
            b"".join(
                path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes()
                for path in sorted((root / "src").rglob("*.py"))
            )
        ).hexdigest(),
        "benchmark_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "inputs": "13 fixed scripted synthetic distributions/failures in this module",
        "uncertainty_treatment": UNCERTAINTY,
        "baseline": rows[0],
        "treatment": rows[1],
        "harness_elapsed_ns": time.perf_counter_ns() - started,
        "fee_basis": {
            "actual_usd": 0.0,
            "reason": "offline scripted responses; no model requests or credential reads",
        },
        "limitations": [
            "Behavioral regression A/B, not model quality, calibration or real website success measurement.",
            "Fixture usage envelopes are simulated; actual model usage is explicitly zero for both arms.",
            "Timing includes complete simulated analysis/hosted operations, not model/network/browser latency.",
            "The treatment deliberately increases review and decreases automatic completion on ambiguous inputs.",
            "No result cache is used. Contracts and thresholds do not authorize actions.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", default=BASELINE)
    parser.add_argument("--output")
    parser.add_argument("--worker", choices=["baseline", "treatment"], help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    result = _worker(args.worker) if args.worker else run(args.baseline)
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
