"""Aggregate recorded whole-operation runs offline, preserving failed and unknown runs."""

import argparse
import csv
import json
import statistics
from pathlib import Path


def mean(values):
    return statistics.mean(values) if values else None


def reduction(baseline, treatment):
    if baseline is None or treatment is None or baseline <= 0:
        return None
    return 100 * (1 - treatment / baseline)


def totals(rows, field, keys, *, complete_field=None):
    return {
        key: sum(row[field][key] for row in rows)
        if rows
        and all(
            type(row.get(field, {}).get(key)) is int
            and row[field][key] >= 0
            and (not complete_field or row.get(complete_field) is True)
            for row in rows
        )
        else None
        for key in keys
    }


def known_totals(rows, field, keys):
    return {
        key: sum(
            row[field][key]
            for row in rows
            if type(row.get(field, {}).get(key)) is int and row[field][key] >= 0
        )
        for key in keys
    }


def arm_summary(rows):
    times = [r["elapsed_ms"] for r in rows if type(r.get("elapsed_ms")) is int]
    contexts = [r["tool_output_bytes"] for r in rows if type(r.get("tool_output_bytes")) is int]
    chars = [r["tool_output_chars"] for r in rows if type(r.get("tool_output_chars")) is int]
    costs = {}
    for field, output in (
        ("cold_api_equivalent_usd", "mean_cold_usd"),
        ("cache_adjusted_api_equivalent_usd", "mean_adjusted_usd"),
    ):
        values = [r[field] for r in rows if type(r.get(field)) in (float, int)]
        costs[output] = mean(values) if len(values) == len(rows) else None
        costs[output + "_measurements"] = len(values)
    main_keys = ("input_tokens", "cached_input_tokens", "output_tokens")
    jev_keys = ("input_tokens", "output_tokens")
    return {
        "runs": len(rows),
        "valid_runs": sum(r.get("valid", False) for r in rows),
        "invalid_runs": sum(not r.get("valid", False) for r in rows),
        "selection_correct": sum(r.get("selection_correct", False) for r in rows),
        "complete_correct": sum(r.get("exact", False) for r in rows),
        "review_runs": sum(r.get("needs_review", True) for r in rows),
        "review_ids_count": sum(len(r.get("review_ids", [])) for r in rows),
        "false_positive_count": sum(len(r.get("false_positive_ids", [])) for r in rows),
        "false_negative_count": sum(len(r.get("false_negative_ids", [])) for r in rows),
        "mean_ms": mean(times),
        "median_ms": statistics.median(times) if times else None,
        "min_ms": min(times) if times else None,
        "max_ms": max(times) if times else None,
        "timed_runs": len(times),
        "mean_context_bytes": mean(contexts),
        "mean_context_chars": mean(chars),
        "context_measurements": len(contexts),
        "main_tokens": totals(rows, "main_usage", main_keys, complete_field="main_usage_complete"),
        "main_known_tokens": known_totals(rows, "main_known_usage", main_keys),
        "jev_tokens": totals(rows, "jev_usage", jev_keys, complete_field="jev_usage_complete"),
        "jev_known_tokens": known_totals(rows, "jev_usage", jev_keys),
        "usage_complete": bool(rows) and all(r.get("usage_complete") is True for r in rows),
        "actual_billed_usd": None,
        **costs,
    }


def summarize(data):
    summary = []
    for model in data["models"]:
        cases = list(dict.fromkeys(r["case"] for r in data["rows"] if r["model"] == model))
        for case in cases:
            item = {"model": model, "case": case}
            for arm in ("raw", "filtered"):
                rows = [
                    r
                    for r in data["rows"]
                    if r["model"] == model and r["case"] == case and r["arm"] == arm
                ]
                item[arm] = arm_summary(rows)
            raw, filtered = item["raw"], item["filtered"]
            item.update(
                context_bytes_reduction_pct=reduction(
                    raw["mean_context_bytes"], filtered["mean_context_bytes"]
                ),
                context_chars_reduction_pct=reduction(
                    raw["mean_context_chars"], filtered["mean_context_chars"]
                ),
                main_input_tokens_reduction_pct=reduction(
                    raw["main_tokens"]["input_tokens"], filtered["main_tokens"]["input_tokens"]
                ),
                cold_cost_reduction_pct=reduction(raw["mean_cold_usd"], filtered["mean_cold_usd"]),
                adjusted_cost_reduction_pct=reduction(
                    raw["mean_adjusted_usd"], filtered["mean_adjusted_usd"]
                ),
                latency_change_pct=(
                    -reduction(raw["mean_ms"], filtered["mean_ms"])
                    if raw["mean_ms"] is not None and filtered["mean_ms"] is not None
                    else None
                ),
            )
            summary.append(item)
    return {
        "schema_version": 2,
        "kind": "whole-operation-summary",
        "timestamp_utc": data.get("timestamp_utc"),
        "scope": data.get("scope"),
        "models": data["models"],
        "cases": data.get("cases"),
        "repeats": data.get("repeats"),
        "result_cache": data.get("result_cache"),
        "main_access": data.get("main_access"),
        "pricing": data.get("pricing"),
        "cost_caveat": data.get("cost_caveat"),
        "latency_denominator": "All timed runs, including failures; untimed failures remain counted.",
        "quality_denominator": "All attempted runs, including failures and review outcomes.",
        "rows": summary,
    }


def markdown(data):
    lines = [
        "| Main model | Scenario | Raw / filtered exact | Tool bytes less | Main input tokens less | Mean latency change | Cold API equivalent less | Cache-adjusted equivalent less |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]

    def percentage(value):
        return "unknown" if value is None else f"{value:+.1f}%"

    for row in data["rows"]:
        arms = [row[arm] for arm in ("raw", "filtered")]
        quality = " / ".join(f"{a['complete_correct']}/{a['runs']}" for a in arms)
        values = [
            row["model"],
            row["case"],
            quality,
            *[
                percentage(row[key])
                for key in (
                    "context_bytes_reduction_pct",
                    "main_input_tokens_reduction_pct",
                    "latency_change_pct",
                    "cold_cost_reduction_pct",
                    "adjusted_cost_reduction_pct",
                )
            ],
        ]
        lines.append("| " + " | ".join(values) + " |")
    lines.extend(["", data.get("cost_caveat") or "Actual billed cost is unknown.", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--markdown")
    parser.add_argument("--csv")
    args = parser.parse_args()
    paths = [Path(p) for p in (args.output, args.markdown, args.csv) if p]
    if any(path.exists() for path in paths):
        parser.error("Use fresh output paths; preserve earlier evidence")
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = summarize(data)
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if args.markdown:
        Path(args.markdown).write_text(markdown(result), encoding="utf-8")
    if args.csv:
        columns = [
            "model",
            "case",
            "arm",
            "repeat",
            "valid",
            "exact",
            "needs_review",
            "elapsed_ms",
            "tool_output_bytes",
            "tool_output_chars",
            "usage_complete",
            "cold_api_equivalent_usd",
            "cache_adjusted_api_equivalent_usd",
            "main_input_tokens",
            "main_cached_input_tokens",
            "main_output_tokens",
            "jev_input_tokens",
            "jev_output_tokens",
        ]
        with Path(args.csv).open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
            writer.writeheader()
            for row in data["rows"]:
                flat = {key: row.get(key) for key in columns}
                for source, prefix in (("main_usage", "main"), ("jev_usage", "jev")):
                    for key, value in row.get(source, {}).items():
                        if prefix + "_" + key in columns:
                            flat[prefix + "_" + key] = value
                writer.writerow(flat)
    print(json.dumps({"kind": result["kind"], "comparisons": len(result["rows"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
