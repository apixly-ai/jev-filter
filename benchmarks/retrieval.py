"""Offline paired collector recall A/B on fixed synthetic code; no model calls."""

import argparse
import hashlib
import json
import platform
import statistics
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from jev_context import __version__
from jev_context.tools import collect_code

FILES = {
    "auth.py": (
        "def persist_token(token):\n    return write_disk(token) # token_anchor\n\n"
        "def renew_session(token):\n    return persist_token(token)\n\n"
        "def refresh_credentials(secret):\n    return save_credentials(secret)\n\n"
        "def display_credentials_help():\n    return 'How to refresh credentials'\n"
    ),
    "policy.py": (
        "def verify_access(user):\n    return user.is_admin # permission_anchor\n\n"
        "def deny_permission(user):\n    return not verify_access(user)\n\n"
        "def permission_notice():\n    return 'Permission denied help'\n"
    ),
    "noise.py": "\n".join(
        f"def render_widget_{index}(value):\n    return value + {index}\n" for index in range(32)
    ),
}
CASES = [
    {
        "id": "credentials_and_caller",
        "pattern": "token_anchor",
        "query": "refresh credentials",
        "expand_callers": True,
        "expected": ["persist_token", "renew_session", "refresh_credentials"],
    },
    {
        "id": "permission_and_caller",
        "pattern": "permission_anchor",
        "query": "deny permission",
        "expand_callers": True,
        "expected": ["verify_access", "deny_permission"],
    },
    {
        "id": "no_lexical_overlap",
        "pattern": "absent_anchor",
        "query": "revoke authorization",
        "expand_callers": False,
        "expected": ["verify_access"],
    },
]


def run(repeats=5):
    if not 1 <= repeats <= 20:
        raise ValueError("repeats must be 1..20")
    runs = []
    with tempfile.TemporaryDirectory(prefix="jev-retrieval-fixture-") as directory:
        root = Path(directory)
        for name, body in FILES.items():
            (root / name).write_bytes(body.encode("utf-8"))
        for repeat in range(repeats):
            for case in CASES:
                order = ("baseline", "treatment") if repeat % 2 == 0 else ("treatment", "baseline")
                for arm in order:
                    started = time.perf_counter()
                    options = (
                        {}
                        if arm == "baseline"
                        else {"query": case["query"], "expand_callers": case["expand_callers"]}
                    )
                    rows, collection = collect_code(root, case["pattern"], **options)
                    elapsed = (time.perf_counter() - started) * 1000
                    selected = sorted({row["symbol"] for row in rows})
                    expected = set(case["expected"])
                    correct = expected.intersection(selected)
                    runs.append(
                        {
                            "case": case["id"],
                            "arm": arm,
                            "repeat": repeat,
                            "elapsed_ms": round(elapsed, 3),
                            "candidate_symbols": selected,
                            "expected_symbols": case["expected"],
                            "recall": len(correct) / len(expected),
                            "precision": len(correct) / len(selected) if selected else 0,
                            "failures": collection.get("retrieval", {}).get("file_errors", []),
                            "scope_incomplete": bool(
                                collection.get("truncated")
                                or collection.get("candidate_limit_reached")
                            ),
                            "source_context_bytes": sum(len(row["text"].encode()) for row in rows),
                            "model_usage": [],
                            "requests": 0,
                            "cost_usd": 0,
                        }
                    )
    summary = {}
    for arm in ("baseline", "treatment"):
        matching = [row for row in runs if row["arm"] == arm]
        summary[arm] = {
            "mean_recall": statistics.mean(row["recall"] for row in matching),
            "mean_precision": statistics.mean(row["precision"] for row in matching),
            "median_elapsed_ms": statistics.median(row["elapsed_ms"] for row in matching),
            "mean_source_context_bytes": statistics.mean(
                row["source_context_bytes"] for row in matching
            ),
            "failures": sum(len(row["failures"]) for row in matching),
            "incomplete_scopes": sum(row["scope_incomplete"] for row in matching),
        }
    return {
        "schema_version": 1,
        "kind": "offline_collector_recall",
        "version": __version__,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.system(),
        "fixture_sha256": hashlib.sha256(
            json.dumps(
                {"files": FILES, "cases": CASES}, sort_keys=True, ensure_ascii=False
            ).encode()
        ).hexdigest(),
        "result_cache": False,
        "model_usage": [],
        "cost_assumption": "No model requests; measured cost is zero for deterministic collection only.",
        "scope": "Whole deterministic collection operation only; fixed synthetic recall labels; not semantic judgment quality or a production speed/cost claim.",
        "limitations": [
            "Lexical recall deliberately fails the no_lexical_overlap case in both arms.",
            "Treatment can increase irrelevant candidates, source context and elapsed time.",
            "Python call clues match names syntactically; they do not resolve imports or dispatch.",
            "No model classification, live credential, browser action or customer data used.",
        ],
        "summary": summary,
        "runs": runs,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    result = run(args.repeats)
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"kind": result["kind"], "summary": result["summary"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
