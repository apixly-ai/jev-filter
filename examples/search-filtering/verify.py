"""Validate tutorial collection and admission offline, without model inference."""

import json
from pathlib import Path

from jev_context import analysis
from jev_context.cli import chunks, normalize
from jev_context.tools import collect_code, collect_logs

HERE = Path(__file__).resolve().parent


def planned(records, filename):
    spec = analysis.validate(json.loads((HERE / filename).read_text(encoding="utf-8")))
    assert analysis.context_admission(spec) is None
    parts = list(chunks(normalize(records)))
    for part, record in zip(parts, records):
        part["source"] = {k: v for k, v in record.items() if k not in ("id", "text")}
    result = analysis.plan(parts, "Validate the tutorial fixture without inference", spec)
    return {
        "records": len(records),
        "planned_requests": len(result["items"]),
        "deferred_ids": list(result["deferred"]),
    }


def main():
    retrieved = json.loads((HERE / "retrieved.json").read_text(encoding="utf-8"))
    search = planned(retrieved, "analysis.json")
    assert search["deferred_ids"] == ["pversion-missing:0"]
    code, code_collection = collect_code(HERE / "code.py", "retry|backoff|TimeoutError")
    assert code_collection["ok"] and not code_collection["candidate_limit_reached"]
    assert {record["symbol"] for record in code} == {"retry_timeouts", "report_timeout", "run_once"}
    code_plan = planned(code, "code-analysis.json")
    assert not code_plan["deferred_ids"]
    logs, log_collection = collect_logs((HERE / "events.jsonl").read_text(encoding="utf-8"))
    assert log_collection["groups"] == 4 and log_collection["parse_errors"] == 0
    logs_plan = planned(logs, "log-analysis.json")
    assert not logs_plan["deferred_ids"]
    print(
        json.dumps(
            {"inference_run": False, "search": search, "code": code_plan, "logs": logs_plan},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
