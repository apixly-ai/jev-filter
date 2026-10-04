"""Opt-in paid, synthetic record workflows with real native Jev distributions.

Runs collection -> context admission -> native inference -> reduction -> freshness
verification. The A/B compares released 0.4 collector options and calibrated decision
policies, not an older binary or a full primary-agent continuation. No result cache.
"""

import argparse
import copy
import hashlib
import json
import platform
import statistics
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from jev_context import __version__, analysis, decision_policy, diff, pool, provider, tools
from jev_context.cli import chunks, normalize
from jev_context.diff import changed_diff_sources, collect_diff

from .retrieval import CASES, FILES

THRESHOLDS = [0.0, 0.55, 0.7, 0.85, 0.95, 0.99]
CODE_CONTEXT = {
    "fixture_facts": "This is a synthetic fixture. write_disk persists its argument; "
    "save_credentials persists its argument; user.is_admin is the administrator authorization "
    "flag. persist_token invokes write_disk. Function bodies are complete. Display/help text "
    "does not perform the operation it describes. A fixture function call is evidence of "
    "invoking that function, not proof of external execution."
}
CODE_TASKS = {
    "credentials_and_caller": "Select functions that persist credentials directly, or invoke "
    "the fixture persist_token function. Exclude functions that merely display help text.",
    "permission_and_caller": "Select functions that decide administrator authorization from "
    "user.is_admin directly, or invoke verify_access to invert that access decision. "
    "Exclude functions that merely display permission help.",
    "no_lexical_overlap": "Select the function that checks the administrator authorization "
    "flag user.is_admin directly. Exclude functions that only call that check or display help.",
}
DIFF_FILES = {
    "auth.py": (
        "def can_manage(user):\n    return user.is_admin\n",
        "def can_manage(user):\n    return True\n",
    ),
    "test_auth.py": (
        "def test_member_cannot_manage():\n    assert can_manage(member) is False\n",
        "def test_member_cannot_manage():\n    assert True\n",
    ),
    "input.py": (
        "def run(value):\n    return execute(sanitize(value))\n",
        "def run(value):\n    return execute(value)\n",
    ),
    "quota.py": (
        "def allowed(balance, amount):\n    return balance >= amount\n",
        "def allowed(balance, amount):\n    return True\n",
    ),
    "strict_auth.py": (
        "def can_read(user):\n    return user.is_admin\n",
        "def can_read(user):\n    return user.is_admin and user.active\n",
    ),
    "logging.py": (
        "def display_error():\n    return 'Failed'\n",
        "def display_error():\n    return 'Authorization failed'\n",
    ),
    "timeout.py": ("TIMEOUT = 10\n", "TIMEOUT = 15\n"),
    "docs.txt": (
        "Authorization errors are shown to users.\n",
        "Authorization errors are shown to users with a helpful explanation.\n",
    ),
}
DIFF_EXPECTED = {
    name: "MATCH" if name in {"auth.py", "test_auth.py", "input.py", "quota.py"} else "EXCLUDE"
    for name in DIFF_FILES
}
DIFF_TASK = (
    "Select complete file changes that weaken authorization, input sanitization, "
    "balance checks or behavioral test assertions compared with the before source. "
    "Exclude stricter checks, display-only wording, documentation and unrelated timing changes."
)
DIFF_CONTEXT = {
    "fixture_facts": "Synthetic complete before/after source. user.is_admin restricts "
    "authorization; active adds another restriction; sanitize escapes untrusted input before "
    "execute; balance >= amount checks sufficient funds. Test member is a non-admin. "
    "The displayed message and timeout constants do not enforce these checks."
}
UNCERTAINTY_TASK = (
    "Classify only whether the CURRENT request failed during DNS, TCP or TLS "
    "connection establishment BEFORE receiving any HTTP response headers. Historical attempts, "
    "successful current requests and errors after HTTP headers do not qualify. "
    "Review when the evidence does not establish the current phase or header receipt."
)
UNCERTAINTY_SPEC = {
    "requirements": [
        {
            "id": "current_establishment",
            "statement": "The CURRENT request failed during DNS, TCP or TLS establishment "
            "before receiving any HTTP response headers.",
            "expected": True,
        }
    ],
    "context": {
        "scope": "Each record is a different synthetic request. Judge only its current "
        "attempt; do not infer missing telemetry. UNKNOWN requires review."
    },
    "required_context": ["scope"],
    "batch_size": 16,
    "contract": {"id": "live-current-establishment", "version": "1"},
}


def uncertainty_fixture():
    """Frozen tri-state labels; no source record or entity crosses the splits."""
    calibration = [
        ("MATCH", "Current request DNS lookup failed; no socket was opened."),
        ("MATCH", "Current TCP connect was refused; no HTTP response was received."),
        ("MATCH", "Current TLS certificate verification failed before sending HTTP."),
        ("MATCH", "Current request exhausted DNS retries. No HTTP headers arrived."),
        ("MATCH", "Current TLS handshake timed out; HTTP was not started."),
        ("MATCH", "当前请求 TCP 建连被拒绝，尚未收到 HTTP 响应。"),
        ("EXCLUDE", "Previous DNS lookup failed. The current request received HTTP 200."),
        ("EXCLUDE", "Current request received HTTP 503 headers after a successful TLS handshake."),
        ("EXCLUDE", "Current request received HTTP 200 headers and then body decoding failed."),
        ("EXCLUDE", "Current TLS completed; HTTP 429 headers were returned."),
        ("EXCLUDE", "Current request connected successfully and received a valid HTTP 201 body."),
        ("EXCLUDE", "历史连接超时，当前请求收到 HTTP 204 响应头。"),
        ("EXCLUDE", "Current request returned HTTP 502 with error text 'upstream DNS failure'."),
        ("EXCLUDE", "Current HTTP stream reset while reading the body after status 200 headers."),
        (
            "REVIEW",
            "Current request failed, but the record does not state the phase or header receipt.",
        ),
        (
            "REVIEW",
            "A DNS failure is logged; the attempt identity and whether it is current are absent.",
        ),
        ("REVIEW", "Current timeout occurred; no phase or HTTP receipt telemetry was recorded."),
        (
            "REVIEW",
            "The current operation is pending; no terminal response or connection status exists.",
        ),
    ]
    holdout = [
        (
            "MATCH",
            "The active attempt could not resolve api.fixture.invalid and stopped before connecting.",
        ),
        (
            "MATCH",
            "The active socket connection hit ECONNREFUSED before any request headers were sent.",
        ),
        (
            "MATCH",
            "The active TLS negotiation returned a handshake alert; no HTTP exchange happened.",
        ),
        (
            "MATCH",
            "Current attempt TCP SYN retries expired; the HTTP client never received headers.",
        ),
        (
            "MATCH",
            "The current resolver returned NXDOMAIN; the HTTP client never started a request.",
        ),
        ("MATCH", "当前这次 TLS 握手校验失败，HTTP 请求尚未发送。"),
        (
            "EXCLUDE",
            "The active attempt received HTTP 504; its response says an earlier connection timed out.",
        ),
        (
            "EXCLUDE",
            "The current attempt got HTTP 200 response headers, then an EOF during body download.",
        ),
        ("EXCLUDE", "The old TLS attempt failed; retry attempt CURRENT received HTTP 202 headers."),
        ("EXCLUDE", "Current request established TLS and got a 401 HTTP response."),
        (
            "EXCLUDE",
            "The active connection is healthy; current request returned a valid HTTP 200 document.",
        ),
        ("EXCLUDE", "当前响应为 HTTP 500，响应正文是 TLS 错误说明。"),
        (
            "EXCLUDE",
            "Current HTTP response was 400 and arrived before request payload validation failed.",
        ),
        ("EXCLUDE", "Earlier ECONNREFUSED was recovered; this current attempt returned HTTP 200."),
        (
            "REVIEW",
            "The active attempt reports network trouble; exact phase and HTTP headers are unknown.",
        ),
        (
            "REVIEW",
            "A TCP refusal happened at an unstated time. Current attempt status is not supplied.",
        ),
        (
            "REVIEW",
            "The active request exceeded its deadline; no connect/response timestamps are available.",
        ),
        (
            "REVIEW",
            "Current attempt is still resolving a host and has not reached a terminal state.",
        ),
    ]
    return [
        {
            "id": f"{split}-{index:02}",
            "text": text,
            "expected": expected,
            "group": f"{split}-family-{index:02}",
            "split": split,
        }
        for split, cases in (("calibration", calibration), ("holdout", holdout))
        for index, (expected, text) in enumerate(cases)
    ]


def quality(decisions, expected):
    selected = {key for key, value in decisions.items() if value == "MATCH"}
    gold = {key for key, value in expected.items() if value == "MATCH"}
    reviewed = {key for key, value in decisions.items() if value == "REVIEW"}
    automatic = {key: value for key, value in decisions.items() if value in {"MATCH", "EXCLUDE"}}
    errors = [key for key, value in automatic.items() if expected.get(key) != value]
    correct = sum(value == expected.get(key) for key, value in decisions.items())
    return {
        "records": len(expected),
        "selected_ids": sorted(selected),
        "review_ids": sorted(reviewed),
        "false_positive_ids": sorted(selected - gold),
        "false_negative_ids": sorted(gold - selected),
        "wrong_automatic_ids": sorted(errors),
        "not_collected_ids": sorted(set(expected) - set(decisions)),
        "correct_decisions": correct,
        "precision": len(selected & gold) / len(selected) if selected else None,
        "recall": len(selected & gold) / len(gold) if gold else None,
        "automatic": len(automatic),
        "automatic_error_rate": len(errors) / len(automatic) if automatic else None,
        "coverage": len(automatic) / len(expected) if expected else 0,
        "exact": set(expected) == set(decisions) and correct == len(expected),
    }


def model_accounting(rows):
    """Known subtotals are not a complete bill when any envelope is missing."""
    models = sorted({row["model"] for row in rows if row.get("ok") and row.get("model")})
    by_model = []
    keys = ("input_tokens", "output_tokens")
    for model in models:
        matches = [row for row in rows if row.get("ok") and row.get("model") == model]
        counts = {key: [row.get("usage", {}).get(key) for row in matches] for key in keys}
        by_model.append(
            {
                "model": model,
                "successful_requests": len(matches),
                "known_usage": {
                    key: sum(value for value in values if type(value) is int and value >= 0)
                    if any(type(value) is int and value >= 0 for value in values)
                    else None
                    for key, values in counts.items()
                },
                "usage_complete": all(row.get("usage_complete") is True for row in matches)
                and all(
                    all(type(value) is int and value >= 0 for value in values)
                    for values in counts.values()
                ),
            }
        )
    return {
        "observed_models": models,
        "known_usage": {key: sum(row["known_usage"][key] or 0 for row in by_model) for key in keys},
        "usage_complete": all(row.get("ok") and row.get("model") for row in rows)
        and all(row["usage_complete"] for row in by_model),
        "failed_request_ids": [row["id"] for row in rows if not row.get("ok")],
        "failures": [
            {
                key: row[key]
                for key in ("id", "error_type", "error", "unknown_usage_attempts")
                if key in row
            }
            for row in rows
            if not row.get("ok")
        ],
        "by_model": by_model,
    }


def native_decision(answer, threshold):
    if not answer or threshold is None:
        return "REVIEW"
    if decision_policy.assess(answer, "current_establishment", {"min_top_probability": threshold}):
        return "REVIEW"
    return {"SUPPORTED": "MATCH", "CONTRADICTED": "EXCLUDE"}.get(answer["choice"], "REVIEW")


def select_policy(calibration, thresholds=None):
    """Maximize automatic coverage with no observed automatic calibration errors."""
    candidates = []
    expected = {row["id"]: row["expected"] for row in calibration}
    for threshold in THRESHOLDS if thresholds is None else thresholds:
        decisions = {
            row["id"]: native_decision(row.get("answer"), threshold) for row in calibration
        }
        candidates.append({"threshold": threshold, "metrics": quality(decisions, expected)})
    eligible = [row for row in candidates if not row["metrics"]["wrong_automatic_ids"]]
    chosen = (
        max(eligible, key=lambda row: (row["metrics"]["automatic"], -row["threshold"]))
        if eligible
        else None
    )
    return {
        "threshold": chosen["threshold"] if chosen else None,
        "selection_source": "calibration_only",
        "status": "selected" if chosen else "all_review_no_eligible_threshold",
        "metrics": chosen["metrics"]
        if chosen
        else quality({key: "REVIEW" for key in expected}, expected),
        "candidates": candidates,
        "objective": "Maximum automatic coverage with zero observed automatic calibration errors; lowest threshold breaks ties.",
    }


def operation(collector, task, spec, expected, *, verify=None, names=None, retain_all=False):
    """Instrument real public pipeline calls; only synthetic IDs and numeric evidence exit."""
    started = time.perf_counter()
    records, collection = collector()
    admitted_at = time.perf_counter()
    # Absolute fixture roots vary per execution and carry no behavioral evidence.
    # Preserve original collector records for the freshness verifier, but send stable
    # fixture-relative path metadata into both model arms.
    model_records = [
        {
            **record,
            **(
                {"path": record.get("relative_path", Path(record["path"]).name)}
                if record.get("path")
                else {}
            ),
        }
        for record in records
    ]
    normalized = normalize(model_records)
    parts = list(chunks(normalized))
    for part, record in zip(parts, normalized):
        part["source"] = {
            key: value for key, value in record.items() if key not in {"id", "text", "sha256"}
        }
    spec = analysis.validate(spec)
    planned = analysis.plan(parts, task, spec)
    captured = []
    actual_run = pool.run

    def observe_pool(*args, **kwargs):
        result = actual_run(*args, **kwargs)
        captured.extend(result["results"])
        return result

    if retain_all:
        planned["items"] = []
        result = {
            "ok": True,
            "complete": True,
            "scope_incomplete": False,
            "selected_ids": [row["id"] for row in records],
            "review_ids": [],
            "excerpts": model_records,
            "telemetry": {
                "requests": 0,
                "usage": {"input_tokens": 0, "output_tokens": 0},
                "usage_complete": True,
                "unknown_usage_attempts": 0,
            },
        }
    else:
        with patch("jev_context.pool.run", side_effect=observe_pool):
            result = tools.analyze_records(
                model_records, task, spec, collection, workers=4, budget=16000
            )
    reduced_at = time.perf_counter()
    if verify:
        result = verify(result, records, collection)
    mapping = names or {record["id"]: record["id"] for record in records}
    decisions = {
        mapping[record["id"]]: "MATCH"
        if record["id"] in result["selected_ids"]
        else "REVIEW"
        if record["id"] in result["review_ids"]
        else "EXCLUDE"
        for record in records
    }
    # Candidate negatives join the fixed positives; label construction never uses model output.
    labels = {**{key: "EXCLUDE" for key in decisions}, **expected}
    native = {}
    source_names = {part["id"]: mapping[part["source_id"]] for part in parts}
    for row in captured:
        if not row.get("ok"):
            continue
        for key, part_id, question in planned["routes"][row["id"]]:
            native.setdefault(source_names[part_id], {})[question] = row["answers"][key]
    packet = {
        "candidate_ids": sorted(decisions),
        "quality": quality(decisions, labels),
        "decisions": decisions,
        "native_answers": native,
        "whole_operation_ms": round((time.perf_counter() - started) * 1000, 3),
        "collection_ms": round((admitted_at - started) * 1000, 3),
        "admission_inference_reduction_ms": round((reduced_at - admitted_at) * 1000, 3),
        "input_source_bytes": sum(len(record["text"].encode()) for record in records),
        "inference_context_bytes": sum(
            analysis.encoded_bytes(item["request"]) for item in planned["items"]
        ),
        "returned_context_bytes": analysis.encoded_bytes(result),
        "scope_incomplete": result["scope_incomplete"],
        "verification_ok": not result.get("changed_sources"),
        "telemetry": result["telemetry"],
        "model_accounting": model_accounting(captured),
    }
    return packet


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _code_fixture(root):
    for name, text in FILES.items():
        (root / name).write_bytes(text.encode())


def _diff_fixture(root):
    _git(root, "init", "-q")
    for key, value in (
        ("user.name", "Synthetic Fixture"),
        ("user.email", "fixture@example.invalid"),
        ("commit.gpgsign", "false"),
        ("core.autocrlf", "false"),
        ("core.hooksPath", str(root / ".git/no-fixture-hooks")),
    ):
        _git(root, "config", key, value)
    for name, (before, _) in DIFF_FILES.items():
        (root / name).write_bytes(before.encode())
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "synthetic baseline")
    base = _git(root, "rev-parse", "HEAD")
    for name, (_, after) in DIFF_FILES.items():
        (root / name).write_bytes(after.encode())
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "synthetic permitted changes")
    return base


def benchmark(*, repeats=2, model="jev-1.13.0", live=False):
    if not 1 <= repeats <= 5:
        raise ValueError("repeats must be 1..5")
    fixture = {
        "code_files": FILES,
        "code_cases": CASES,
        "diff_files": DIFF_FILES,
        "diff_expected": DIFF_EXPECTED,
        "uncertainty": uncertainty_fixture(),
    }
    result = {
        "schema_version": 1,
        "kind": "live_synthetic_record_workflows" if live else "offline_live_record_plan",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "version": __version__,
        "requested_model": model,
        "python": platform.python_version(),
        "platform": platform.system(),
        "fixture_sha256": hashlib.sha256(
            json.dumps(fixture, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest(),
        "runtime_source_sha256": {
            module.__name__: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for module in (analysis, decision_policy, diff, pool, provider, tools)
        },
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "result_cache": False,
        "max_workers": 4,
        "inference_enabled": live,
        "scope": "Whole synthetic record operations including collection, admission, native inference, reduction and source freshness. Excludes a primary agent continuation, customer data, browser/desktop actions and invoice reconciliation.",
        "arms": {
            "code": "Same 0.4.0 exact rg collector vs opt-in lexical/symbol/caller recall; both use the same native semantic filter.",
            "diff": "All changed files retained deterministically vs native semantic triage of full before/after evidence; not a human reviewer quality comparison.",
            "uncertainty": "Default zero thresholds vs threshold chosen using a separate native calibration sample. Each holdout arm obtains fresh inference; no saved judgment serves as a live model result.",
        },
        "limitations": [
            "Lexical recall cannot retrieve the deliberately absent-token no-overlap case.",
            "Recall can add irrelevant candidates, context bytes, model tokens and latency.",
            "Fixed small synthetic scenarios do not establish production or whole-agent savings.",
            "Threshold selection is observed sample admission, not a fitted probability calibrator or a population accuracy guarantee.",
            "Calibration and holdout use distinct source records but cover similar handwritten connection scenarios; this is not an out-of-distribution generalization study.",
            "Native token envelopes are actual provider usage; USD conversion needs a separate verified price and is not invoice proof.",
        ],
        "runs": [],
    }
    if not live:
        return result
    with tempfile.TemporaryDirectory(prefix="jev-paid-code-") as directory:
        root = Path(directory)
        _code_fixture(root)
        for repeat in range(repeats):
            for case in CASES:
                for arm in (
                    ("baseline", "treatment") if repeat % 2 == 0 else ("treatment", "baseline")
                ):
                    options = (
                        {}
                        if arm == "baseline"
                        else {"query": case["query"], "expand_callers": case["expand_callers"]}
                    )

                    def collector(options=options, case=case):
                        return tools.collect_code(root, case["pattern"], **options)

                    rows, _ = collector()
                    names = {row["id"]: row["symbol"] for row in rows}
                    packet = operation(
                        collector,
                        CODE_TASKS[case["id"]],
                        {
                            "model": model,
                            "context": CODE_CONTEXT,
                            "required_context": ["fixture_facts"],
                            "requirements": [
                                {
                                    "id": "implements_operation",
                                    "statement": "The target function meets the concrete selection criteria stated in the task, including the task's exclusion criteria.",
                                    "expected": True,
                                }
                            ],
                        },
                        {symbol: "MATCH" for symbol in case["expected"]},
                        verify=lambda output, records, meta: tools.guard_code_sources(
                            output, records
                        ),
                        names=names,
                    )
                    result["runs"].append(
                        {
                            "workflow": "code",
                            "case": case["id"],
                            "arm": arm,
                            "repeat": repeat,
                            **packet,
                        }
                    )
    with tempfile.TemporaryDirectory(prefix="jev-paid-diff-") as directory:
        root = Path(directory)
        base = _diff_fixture(root)

        def collector():
            return collect_diff(root, base=base)

        rows, _ = collector()
        names = {row["id"]: row["relative_path"] for row in rows}

        def verify_diff(output, records, meta):
            changed = changed_diff_sources(records, meta)
            if changed:
                output["changed_sources"] = changed
                output["selected_ids"] = [
                    rid for rid in output["selected_ids"] if rid not in changed
                ]
                output["review_ids"] = list(dict.fromkeys(output["review_ids"] + changed))
                output["complete"] = False
            return output

        for repeat in range(repeats):
            for arm in ("baseline", "treatment") if repeat % 2 == 0 else ("treatment", "baseline"):
                spec = (
                    {"mode": "passthrough"}
                    if arm == "baseline"
                    else {
                        "model": model,
                        "context": DIFF_CONTEXT,
                        "required_context": ["fixture_facts"],
                        "requirements": [
                            {
                                "id": "weakens_check",
                                "statement": "The target file change weakens authorization, input sanitization, a balance check or a behavioral test assertion compared with the before source.",
                                "expected": True,
                            }
                        ],
                    }
                )
                packet = operation(
                    collector,
                    DIFF_TASK,
                    spec,
                    DIFF_EXPECTED,
                    verify=verify_diff,
                    names=names,
                    retain_all=arm == "baseline",
                )
                result["runs"].append(
                    {
                        "workflow": "diff",
                        "case": "weakened_checks",
                        "arm": arm,
                        "repeat": repeat,
                        **packet,
                    }
                )
    records = uncertainty_fixture()

    def collector_for(split):
        selected = [row for row in records if row["split"] == split]
        return lambda: (
            [
                {
                    key: value
                    for key, value in row.items()
                    if key not in {"expected", "split", "group"}
                }
                for row in selected
            ],
            {"ok": True},
        ), {row["id"]: row["expected"] for row in selected}

    cal_collector, calibration_expected = collector_for("calibration")
    cal_packet = operation(
        cal_collector, UNCERTAINTY_TASK, {**UNCERTAINTY_SPEC, "model": model}, calibration_expected
    )
    result["calibration_run"] = cal_packet
    calibration = [
        {
            "id": row["id"],
            "expected": row["expected"],
            "answer": cal_packet["native_answers"].get(row["id"], {}).get("current_establishment"),
        }
        for row in records
        if row["split"] == "calibration"
    ]
    policy = select_policy(calibration)
    result["policy_selection"] = policy
    hold_collector, expected = collector_for("holdout")
    for repeat in range(repeats):
        for arm in ("baseline", "treatment") if repeat % 2 == 0 else ("treatment", "baseline"):
            spec = copy.deepcopy({**UNCERTAINTY_SPEC, "model": model})
            if arm == "treatment":
                spec["uncertainty"] = {
                    "min_top_probability": policy["threshold"]
                    if policy["threshold"] is not None
                    else 1.0
                }
            packet = operation(hold_collector, UNCERTAINTY_TASK, spec, expected)
            if arm == "treatment" and policy["threshold"] is None:
                # No satisfying policy: reject all automatic outputs, including native p=1.
                packet["decisions"] = {key: "REVIEW" for key in expected}
                packet["quality"] = quality(packet["decisions"], expected)
            result["runs"].append(
                {
                    "workflow": "uncertainty",
                    "case": "held_out_current_establishment",
                    "arm": arm,
                    "repeat": repeat,
                    **packet,
                }
            )
    result["summary"] = summarize(result)
    return result


def summarize(result):
    summary = {}
    for workflow in ("code", "diff", "uncertainty"):
        summary[workflow] = {}
        for arm in ("baseline", "treatment"):
            rows = [
                row for row in result["runs"] if row["workflow"] == workflow and row["arm"] == arm
            ]
            summary[workflow][arm] = {
                "operations": len(rows),
                "median_whole_operation_ms": statistics.median(
                    row["whole_operation_ms"] for row in rows
                ),
                "false_positive": sum(len(row["quality"]["false_positive_ids"]) for row in rows),
                "false_negative": sum(len(row["quality"]["false_negative_ids"]) for row in rows),
                "review": sum(len(row["quality"]["review_ids"]) for row in rows),
                "failed_requests": sum(
                    len(row["model_accounting"]["failed_request_ids"]) for row in rows
                ),
                "exact_operations": sum(row["quality"]["exact"] for row in rows),
                "inference_context_bytes": sum(row["inference_context_bytes"] for row in rows),
                "known_usage": {
                    key: sum(row["model_accounting"]["known_usage"][key] for row in rows)
                    for key in ("input_tokens", "output_tokens")
                },
                "usage_complete": all(
                    row["model_accounting"]["usage_complete"]
                    and row["telemetry"].get("usage_complete") is True
                    for row in rows
                ),
                "observed_models": sorted(
                    {model for row in rows for model in row["model_accounting"]["observed_models"]}
                ),
            }
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="Opt in to billable native Jev requests"
    )
    parser.add_argument("--model", default="jev-1.13.0")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    destination = Path(args.output)
    if destination.exists():
        parser.error("output exists; preserve earlier evidence")
    result = benchmark(repeats=args.repeats, model=args.model, live=args.live)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {
                "kind": result["kind"],
                "summary": result.get("summary", {}),
                "calibration_policy": result.get("policy_selection", {}).get("threshold"),
            },
            allow_nan=False,
        )
    )
    return (
        2
        if any(
            not row["verification_ok"] or row["model_accounting"]["failed_request_ids"]
            for row in result["runs"]
        )
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
