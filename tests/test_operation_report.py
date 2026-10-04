"""Publication aggregates retain missing evidence and failed-run denominators."""

from benchmarks.operation_report import summarize


def row(arm, **changes):
    return {
        "model": "fixture",
        "case": "exec",
        "arm": arm,
        "repeat": 0,
        "valid": True,
        "selection_correct": True,
        "exact": True,
        "needs_review": False,
        "elapsed_ms": 100,
        "tool_output_bytes": 100 if arm == "raw" else 10,
        "tool_output_chars": 100 if arm == "raw" else 10,
        "main_usage": {"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 1},
        "main_known_usage": {"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 1},
        "jev_usage": {"input_tokens": 0, "output_tokens": 0},
        "main_usage_complete": True,
        "jev_usage_complete": True,
        "usage_complete": True,
        "cold_api_equivalent_usd": None,
        "cache_adjusted_api_equivalent_usd": None,
        **changes,
    }


def test_unknown_counts_and_absent_prices_never_aggregate_as_zero():
    data = {
        "models": ["fixture"],
        "rows": [
            row("raw"),
            row(
                "filtered",
                main_usage={"input_tokens": 10, "cached_input_tokens": None, "output_tokens": None},
                main_known_usage={"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 1},
                main_usage_complete=False,
                usage_complete=False,
            ),
        ],
    }
    result = summarize(data)["rows"][0]
    assert result["filtered"]["main_tokens"]["output_tokens"] is None
    assert result["filtered"]["main_known_tokens"]["output_tokens"] == 1
    assert result["filtered"]["usage_complete"] is False
    assert result["context_bytes_reduction_pct"] == 90
    assert result["cold_cost_reduction_pct"] is None


def test_failed_runs_keep_quality_and_latency_denominators():
    data = {
        "models": ["fixture"],
        "rows": [
            row("raw"),
            row("filtered"),
            row(
                "filtered",
                repeat=1,
                valid=False,
                selection_correct=False,
                exact=False,
                needs_review=True,
                elapsed_ms=300,
                tool_output_bytes=None,
                tool_output_chars=None,
            ),
        ],
    }
    result = summarize(data)["rows"][0]["filtered"]
    assert result["runs"] == 2
    assert result["valid_runs"] == 1
    assert result["complete_correct"] == 1
    assert result["review_runs"] == 1
    assert result["mean_ms"] == 200
    assert result["context_measurements"] == 1


def test_empty_receipt_arm_has_no_fabricated_timing_or_context():
    data = {"models": ["fixture"], "rows": [row("raw")]}
    result = summarize(data)["rows"][0]
    assert result["filtered"]["runs"] == 0
    assert result["filtered"]["mean_ms"] is None
    assert result["filtered"]["usage_complete"] is False
    assert result["context_bytes_reduction_pct"] is None
