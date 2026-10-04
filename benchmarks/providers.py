"""Opt-in, same-input Jev/LLM comparison through the official System One Adapter.

No model calls by default. --live requires explicit provider/model selection and
externally supplied credentials. Debug traces and provider bodies never enter output.
"""

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from jev_context import analysis, validation

from .fixture import SPEC, TASK, fixture


def normalize_adapter(response):
    usage = response.get("usage") or {}
    counts = {k: usage.get(k + "_total") for k in ("input_tokens", "output_tokens")}
    complete = all(type(v) is int and v >= 0 for v in counts.values())
    return {
        "ok": True,
        "model": response["model"],
        "answers": response["answers"],
        "usage": counts,
        "usage_complete": complete,
        "attempts": 1 + usage.get("n_retries", 0),
        "probability_basis": "LLM generated probabilities, not native Jev probabilities",
    }


def run(body, provider, model):
    if provider == "jev":
        from jev_context.provider import Client

        with Client() as client:
            return client.call({**body, "model": model})
    from system_one_adapter import SystemOneAdapterClient

    with SystemOneAdapterClient(structured_outputs=True, llm_answer_mode="probabilities") as client:
        response = client.system_one(
            state=body["state"], questions=body["questions"], provider=provider, model=model
        )
        result = normalize_adapter(response.model_dump())
    # Validate typed answers using a validation-only usage envelope. Reporting below
    # preserves None from the adapter; this envelope is never reported as real usage.
    validation.validate_response(body, {**result, "usage": {"input_tokens": 0, "output_tokens": 0}})
    return result


def benchmark(provider, model, records=32, repeats=2, live=False):
    parts, gold = fixture(records)
    spec = analysis.validate({**SPEC, "model": "jev-1.13.0"})
    plan = analysis.plan(parts, TASK, spec)
    runs = []
    if live:
        for repeat in range(repeats):
            start = time.perf_counter()
            judgments, failures = {}, []
            totals = {"input_tokens": 0, "output_tokens": 0}
            known = True
            attempts = 0
            observed_models = set()
            for item in plan["items"]:
                try:
                    result = run(item["request"], provider, model)
                    observed_models.add(result["model"])
                    attempts += result.get("attempts", 1)
                    known &= result["usage_complete"]
                    for key in totals:
                        count = result["usage"].get(key)
                        if type(count) is int:
                            totals[key] += count
                    for key, part_id, question in plan["routes"][item["id"]]:
                        entry = judgments.setdefault(part_id, {"status": "OK", "answers": {}})
                        entry["answers"][question] = result["answers"][key]
                except Exception as error:
                    known = False
                    attempts += getattr(error, "unknown_usage_attempts", 1)
                    failures.append({"request_id": item["id"], "error_type": type(error).__name__})
            result = analysis.summarize(parts, judgments, spec)
            selected = set(result["selected_ids"])
            expected = set(gold)
            runs.append(
                {
                    "repeat": repeat,
                    "elapsed_ms": round((time.perf_counter() - start) * 1000),
                    "selected_ids": result["selected_ids"],
                    "review_ids": result["review_ids"],
                    "false_positive_ids": sorted(selected - expected),
                    "false_negative_ids": sorted(expected - selected),
                    "exact": result["complete"] and selected == expected,
                    "failures": failures,
                    "known_usage": totals,
                    "usage_complete": known,
                    "attempts": attempts,
                    "observed_models": sorted(observed_models),
                }
            )
    encoded = json.dumps(parts, sort_keys=True, ensure_ascii=False).encode()
    return {
        "kind": "live_provider_comparison_arm" if live else "offline_provider_plan",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "model": model,
        "fixture_sha256": hashlib.sha256(encoded).hexdigest(),
        "expected_ids": gold,
        "input_records": records,
        "context_bytes_per_operation": sum(
            analysis.encoded_bytes(i["request"]) for i in plan["items"]
        ),
        "planned_requests": len(plan["items"]),
        "result_cache": False,
        "probability_basis": "native Jev"
        if provider == "jev"
        else "LLM generated; separately calibrated",
        "inference_enabled": live,
        "actual_usage_available": any(r["observed_models"] for r in runs),
        "runs": runs,
        "scope": "Synthetic fixed semantic filtering operation; excludes a primary agent continuation. No whole-agent savings claim.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider", choices=["jev", "openai", "anthropic", "gemini"], required=True
    )
    parser.add_argument("--model", required=True)
    parser.add_argument("--records", type=int, default=32)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not 1 <= args.records <= 512 or not 1 <= args.repeats <= 10:
        parser.error("records 1..512 and repeats 1..10")
    target = Path(args.output)
    if target.exists():
        parser.error("output exists; preserve earlier evidence")
    data = benchmark(args.provider, args.model, args.records, args.repeats, args.live)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {"kind": data["kind"], "requests": data["planned_requests"], "runs": len(data["runs"])}
        )
    )
    return 2 if data["runs"] and not all(r["exact"] for r in data["runs"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
