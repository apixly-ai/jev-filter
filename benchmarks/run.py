"""Run planning checks offline, or a billable paired Jev benchmark with --live."""

import argparse
import hashlib
import json
import platform
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from jev_context import __version__, analysis

from .fixture import SPEC, TASK, fixture


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--live", action="store_true")
    p.add_argument("--output", required=True)
    p.add_argument("--records", type=int, default=96)
    p.add_argument("--repeats", type=int, default=2)
    p.add_argument(
        "--parallel-workers", type=int, default=30, help="1..30; lower when sharing a test budget"
    )
    a = p.parse_args()
    if not 1 <= a.records <= 512 or not 1 <= a.repeats <= 10:
        p.error("records 1..512 and repeats 1..10 required")
    if not 1 <= a.parallel_workers <= 30:
        p.error("parallel-workers 1..30 required")
    target = Path(a.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        p.error("output exists; use a new path to retain prior runs")
    records, gold = fixture(a.records)
    configurations = [
        ("single_serial", 1, 1),
        ("batch_serial", "auto", 1),
        ("single_parallel", 1, a.parallel_workers),
        ("batch_parallel", "auto", a.parallel_workers),
    ]
    rows = []
    for repeat in range(a.repeats if a.live else 1):
        for name, size, workers in (
            configurations if repeat % 2 == 0 else list(reversed(configurations))
        ):
            spec = {**SPEC, "batch_size": size}
            start = time.perf_counter()
            if a.live:
                judgments, stats = analysis.evaluate(records, TASK, workers=workers, spec=spec)
                result = analysis.summarize(records, judgments, analysis.validate(spec))
                correct = result["complete"] and set(result["selected_ids"]) == set(gold)
                row = {
                    "name": name,
                    "repeat": repeat,
                    "elapsed_ms": round((time.perf_counter() - start) * 1000),
                    "exact": correct,
                    "result": result,
                    "telemetry": stats,
                }
            else:
                plan = analysis.plan(records, TASK, spec)
                row = {
                    "name": name,
                    "planned_requests": len(plan["items"]),
                    "requested_workers": workers,
                    "deferred": len(plan["deferred"]),
                }
            rows.append(row)
            print(
                json.dumps({k: v for k, v in row.items() if k not in ("result", "telemetry")}),
                flush=True,
            )
    result = {
        "schema_version": 1,
        "kind": "live" if a.live else "offline_planning",
        "version": __version__,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.system(),
        "python": platform.python_version(),
        "records": a.records,
        "questions_per_record": 2,
        "model": "jev-1.13.0",
        "result_cache": False,
        "concurrency_cap": 30,
        "parallel_workers": a.parallel_workers,
        "fixture_sha256": hashlib.sha256(
            json.dumps(records, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest(),
        "runs": rows,
    }
    if a.live:
        result["summary"] = {
            name: {
                "mean_ms": statistics.mean(r["elapsed_ms"] for r in rows if r["name"] == name),
                "complete_correct_runs": sum(r["exact"] for r in rows if r["name"] == name),
                "known_input_tokens": sum(
                    r["telemetry"]["usage"]["input_tokens"] for r in rows if r["name"] == name
                ),
                "usage_complete": all(
                    r["telemetry"]["usage_complete"] for r in rows if r["name"] == name
                ),
            }
            for name, _, _ in configurations
        }
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if not a.live or all(r["exact"] for r in rows) else 2


if __name__ == "__main__":
    raise SystemExit(main())
