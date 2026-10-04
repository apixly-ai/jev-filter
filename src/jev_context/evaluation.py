"""Offline, group-separated held-out threshold evaluation of saved binary judgments.

This evaluates supplied probabilities. It does not fit a probability calibrator, contact a
model, estimate unseen correctness, or turn a threshold into permission to act.
"""

import argparse
import hashlib
import json
import math
import re
import time
from pathlib import Path

from .validation import number


def _records(payload):
    if (
        not isinstance(payload, dict)
        or type(payload.get("version")) is not int
        or payload["version"] != 1
    ):
        raise ValueError("evaluation input needs version 1")
    if not isinstance(payload.get("model"), str) or not 1 <= len(payload["model"].strip()) <= 160:
        raise ValueError("evaluation input needs model identity")
    contract = payload.get("contract")
    if (
        not isinstance(contract, dict)
        or any(
            not isinstance(contract.get(k), str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}", contract[k])
            for k in ("id", "version")
        )
        or not re.fullmatch(r"[0-9a-f]{64}", str(contract.get("fingerprint", "")))
    ):
        raise ValueError("evaluation input needs contract id/version/fingerprint")
    source = payload.get("records")
    if not isinstance(source, list) or not source or len(source) > 100000:
        raise ValueError("evaluation input needs 1..100000 labeled records")
    records, ids, groups = [], set(), {}
    for raw in source:
        if not isinstance(raw, dict) or any(
            not isinstance(raw.get(key), str) or not raw[key] or len(raw[key]) > 256
            for key in ("id", "group")
        ):
            raise ValueError("record needs bounded id/group")
        if raw["id"] in ids:
            raise ValueError("evaluation record IDs must be unique")
        ids.add(raw["id"])
        split = raw.get("split")
        if split not in ("calibration", "holdout") or type(raw.get("label")) is not bool:
            raise ValueError("record needs calibration/holdout split and boolean label")
        if raw["group"] in groups and groups[raw["group"]] != split:
            raise ValueError("a group cannot appear in both splits")
        groups[raw["group"]] = split
        if (
            raw.get("model", payload["model"]) != payload["model"]
            or raw.get("contract_fingerprint", contract["fingerprint"]) != contract["fingerprint"]
        ):
            raise ValueError("mixed model/contract records require separate evaluations")
        if not isinstance(raw.get("status", "ok"), str):
            raise ValueError("record status must be ok/failed/review/unavailable")
        status = raw.get("status", "ok").lower()
        if status not in ("ok", "failed", "review", "unavailable"):
            raise ValueError("record status must be ok/failed/review/unavailable")
        probability = raw.get("probability")
        if "probability" not in raw and isinstance(raw.get("answer"), dict):
            answer = raw["answer"]
            if answer.get("type") == "noul":
                probability = answer.get("noul")
            elif answer.get("type") == "choice":
                positive = payload.get("positive_label")
                if not isinstance(positive, str) or not positive:
                    raise ValueError("native choice evaluation needs positive_label")
                distribution = answer.get("probabilities")
                if not isinstance(distribution, dict) or positive not in distribution:
                    raise ValueError("native choice probability needs positive_label distribution")
                if (
                    not all(number(v) for v in distribution.values())
                    or abs(sum(distribution.values()) - 1) > 0.03
                ):
                    raise ValueError("invalid native answer probability distribution")
                probability = distribution[positive]
        if probability is not None and not number(probability):
            raise ValueError("record probability must be a finite number in 0..1")
        records.append(
            {
                "id": raw["id"],
                "group": raw["group"],
                "split": split,
                "label": raw["label"],
                "probability": probability,
                "status": status,
            }
        )
    if {r["split"] for r in records} != {"calibration", "holdout"}:
        raise ValueError("evaluation requires nonempty calibration and holdout splits")
    return records


def _disposition(record, threshold):
    probability = record["probability"]
    if record["status"] != "ok":
        return "REVIEW", "source_" + record["status"]
    if probability is None:
        return "REVIEW", "missing_probability"
    if probability + 1e-12 >= threshold:
        return "MATCH", None
    if probability <= 1 - threshold + 1e-12:
        return "EXCLUDE", None
    return "REVIEW", "below_threshold"


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def _usage_snapshot(usage):
    """Only numeric accounting may cross into a public evaluation report."""
    if not isinstance(usage, dict):
        return {"usage_complete": False, "reason": "not_supplied"}
    counts = usage.get("usage", usage)
    result = {}
    for key in ("input_tokens", "output_tokens"):
        value = counts.get(key) if isinstance(counts, dict) else None
        if type(value) is int and value >= 0:
            result[key] = value
    unknown = usage.get("unknown_usage_attempts")
    complete = (
        usage.get("usage_complete") is True
        and len(result) == 2
        and ("unknown_usage_attempts" not in usage or type(unknown) is int and unknown == 0)
    )
    result["usage_complete"] = complete
    if type(unknown) is int and unknown >= 0:
        result["unknown_usage_attempts"] = unknown
    if not complete:
        result["reason"] = "source_usage_incomplete_or_missing"
    return result


def _metrics(records, threshold, bins=10):
    # A review can have a known distribution; dropping it would bias calibration diagnostics
    # toward accepted judgments. Failed/unavailable distributions remain unknown.
    available = [
        r for r in records if r["status"] in ("ok", "review") and r["probability"] is not None
    ]
    counts = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
    review = 0
    for record in records:
        decision, _ = _disposition(record, threshold)
        if decision == "REVIEW":
            review += 1
        else:
            counts[
                ("t" if (decision == "MATCH") == record["label"] else "f")
                + ("p" if decision == "MATCH" else "n")
            ] += 1
    positive = sum(r["label"] for r in records)
    negative = len(records) - positive
    automatic = len(records) - review
    correct = counts["tp"] + counts["tn"]
    precision = _ratio(counts["tp"], counts["tp"] + counts["fp"])
    recall = _ratio(counts["tp"], positive)
    brier = _ratio(sum((r["probability"] - r["label"]) ** 2 for r in available), len(available))
    reliability = []
    ece = 0.0
    for index in range(bins):
        bucket = [r for r in available if min(bins - 1, int(r["probability"] * bins)) == index]
        if not bucket:
            continue
        mean = sum(r["probability"] for r in bucket) / len(bucket)
        rate = sum(r["label"] for r in bucket) / len(bucket)
        ece += len(bucket) / len(available) * abs(mean - rate)
        reliability.append(
            {"bin": index, "count": len(bucket), "mean_probability": mean, "positive_rate": rate}
        )
    return {
        "records": len(records),
        "probability_records": len(available),
        "positive": positive,
        "negative": negative,
        "automatic": automatic,
        "review": review,
        "failed": sum(r["status"] in ("failed", "unavailable") for r in records),
        "missing_probability": sum(
            r["status"] == "ok" and r["probability"] is None for r in records
        ),
        "coverage": automatic / len(records),
        "automatic_accuracy": _ratio(correct, automatic),
        "automatic_error_rate": _ratio(automatic - correct, automatic),
        "precision": precision,
        "recall": recall,
        "specificity": _ratio(counts["tn"], negative),
        "f1": 2 * precision * recall / (precision + recall) if precision and recall else 0.0,
        "brier": brier,
        "ece": ece if available else None,
        "confusion": counts,
        "reliability_bins": reliability,
    }


def evaluate(payload, *, thresholds=None, max_error_rate=0.1, bins=10):
    """Choose from fixed thresholds using calibration groups only; report untouched holdout."""
    started = time.perf_counter()
    records = _records(payload)
    thresholds = [0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0] if thresholds is None else thresholds
    if (
        not isinstance(thresholds, list)
        or not thresholds
        or any(not number(t, 0.5, 1) for t in thresholds)
    ):
        raise ValueError("thresholds must contain finite numbers in 0.5..1")
    if not number(max_error_rate) or type(bins) is not int or not 2 <= bins <= 100:
        raise ValueError("max-error-rate needs 0..1 and bins needs 2..100")
    calibration = [r for r in records if r["split"] == "calibration"]
    holdout = [r for r in records if r["split"] == "holdout"]
    candidates = [
        {"threshold": t, **_metrics(calibration, t, bins)} for t in sorted(set(thresholds))
    ]
    eligible = [
        r
        for r in candidates
        if r["automatic_error_rate"] is None or r["automatic_error_rate"] <= max_error_rate
    ]
    chosen = max(eligible, key=lambda r: (r["coverage"], -r["threshold"])) if eligible else None
    # No satisfying candidate means full review, even for endpoints with p == 0 or 1.
    threshold = chosen["threshold"] if chosen else None
    selected_threshold = threshold if threshold is not None else math.inf
    input_bytes = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode()
    dispositions = []
    for record in records:
        decision, reason = _disposition(record, selected_threshold)
        dispositions.append(
            {
                "id": record["id"],
                "group": record["group"],
                "split": record["split"],
                "decision": decision,
                **({"reason": reason} if reason else {}),
            }
        )
    return {
        "version": 1,
        "ok": True,
        "method": "held_out_threshold_evaluation",
        "model": payload["model"],
        "contract": {key: payload["contract"][key] for key in ("id", "version", "fingerprint")},
        "input_sha256": hashlib.sha256(input_bytes).hexdigest(),
        "selection": {
            "threshold": threshold,
            "source": "calibration_only",
            "max_error_rate": max_error_rate,
            "objective": "maximum automatic coverage within supplied calibration error-rate ceiling",
            "tie_break": "lowest satisfying threshold when calibration coverage ties",
            "status": "selected" if chosen else "all_review_no_eligible_threshold",
        },
        "calibration_candidates": candidates,
        "calibration": _metrics(calibration, selected_threshold, bins),
        "holdout": _metrics(holdout, selected_threshold, bins),
        "dispositions": dispositions,
        "source_inference_usage": _usage_snapshot(payload.get("usage")),
        "evaluation_usage": {
            "requests": 0,
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "usage_complete": True,
        },
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "limitations": [
            "No probability calibration is fitted. Thresholds are evaluated on supplied labels only.",
            "Calibration error-rate ceiling is an observed sample constraint, not a population guarantee.",
            "Recall includes review and failed positives; precision is over automatic positives.",
            "Brier and ECE exclude unavailable probabilities; failures remain in coverage denominators.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(prog="jev-filter eval", description=__doc__)
    parser.add_argument("--input", required=True, help="Versioned saved labeled judgment dataset")
    parser.add_argument("--output", help="Write full JSON report; stdout carries a compact receipt")
    parser.add_argument(
        "--threshold", type=float, action="append", help="Candidate floor in 0.5..1 (repeatable)"
    )
    parser.add_argument("--max-error-rate", type=float, default=0.1)
    parser.add_argument("--bins", type=int, default=10)
    args = parser.parse_args(argv)
    raw = Path(args.input).read_bytes()
    if len(raw) > 64 * 1024 * 1024:
        raise ValueError("evaluation input exceeds 64 MiB")
    result = evaluate(
        json.loads(raw),
        thresholds=args.threshold,
        max_error_rate=args.max_error_rate,
        bins=args.bins,
    )
    # The CLI binds provenance to the exact saved bytes as well as the normalized data hash.
    result["input_file_sha256"] = hashlib.sha256(raw).hexdigest()
    if args.output:
        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        result["output"] = str(output)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        packet = {
            key: result[key]
            for key in (
                "ok",
                "method",
                "model",
                "contract",
                "input_sha256",
                "input_file_sha256",
                "selection",
                "holdout",
                "evaluation_usage",
                "elapsed_ms",
                "output",
            )
        }
    else:
        packet = result
    print(json.dumps(packet, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0
