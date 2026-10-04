"""Whole-operation reports preserve unknown accounting and measured UTF-8 context."""

import json

import pytest

from benchmarks.operations import cost_estimates, load_rate_snapshot, parse_events


def event_lines(usage, output="{}", answer=None):
    return [
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "command": "python /fixture/operation_entry.py /fixture/config.json",
                    "exit_code": 0,
                    "aggregated_output": output,
                },
            }
        ),
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": json.dumps(answer or {"selected_ids": [], "needs_review": False}),
                },
            }
        ),
        json.dumps({"type": "turn.completed", "usage": usage}),
    ]


def test_missing_main_usage_stays_unknown_and_never_priced_as_zero():
    result = parse_events(event_lines({"input_tokens": 10}), "/fixture/operation_entry.py")
    assert result["main_usage"] == {
        "input_tokens": 10,
        "cached_input_tokens": None,
        "output_tokens": None,
    }
    assert result["main_usage_complete"] is False
    costs = cost_estimates(result["main_usage"], {"input_tokens": 0, "output_tokens": 0}, None)
    assert costs["cold_api_equivalent_usd"] is None
    assert costs["cache_adjusted_api_equivalent_usd"] is None
    assert costs["actual_billed_usd"] is None


def test_unicode_context_reports_bytes_separately_from_characters():
    payload = json.dumps({"records": [{"id": "one", "text": "中文"}]}, ensure_ascii=False)
    result = parse_events(
        event_lines({"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 0}, payload),
        "/fixture/operation_entry.py",
    )
    assert result["tool_output_chars"] == len(payload)
    assert result["tool_output_bytes"] == len(payload.encode("utf-8"))
    assert result["tool_output_bytes"] > result["tool_output_chars"]
    assert result["main_usage_complete"] is True


def test_partial_turn_preserves_known_counts_without_claiming_total_complete():
    lines = event_lines({"input_tokens": 10, "cached_input_tokens": 4, "output_tokens": 1})
    lines.append(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 3}}))
    result = parse_events(lines, "/fixture/operation_entry.py")
    assert result["main_usage"]["input_tokens"] == 13
    assert result["main_usage"]["output_tokens"] is None
    assert result["main_known_usage"]["output_tokens"] == 1
    assert result["main_usage_complete"] is False


@pytest.mark.parametrize("invalid", [True, -1, 1.5, "10"])
def test_noninteger_or_negative_token_counts_remain_unknown(invalid):
    result = parse_events(
        event_lines({"input_tokens": invalid, "cached_input_tokens": 0, "output_tokens": 0}),
        "/fixture/operation_entry.py",
    )
    assert result["main_usage"]["input_tokens"] is None
    assert result["main_usage_complete"] is False


def test_invalid_cached_token_count_is_not_negative_cost():
    result = parse_events(
        event_lines({"input_tokens": 10, "cached_input_tokens": 11, "output_tokens": 1}),
        "/fixture/operation_entry.py",
    )
    assert result["main_usage_complete"] is False
    assert result["main_usage"]["cached_input_tokens"] is None


def test_malformed_answer_does_not_pass_receipt_validation():
    result = parse_events(
        event_lines(
            {"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 1},
            answer={"selected_ids": "one", "needs_review": False},
        ),
        "/fixture/operation_entry.py",
    )
    assert result["answer"] is None


def test_costs_require_explicit_rate_snapshot_and_complete_usage():
    rates = {
        "main": {"input": 2, "cached_input": 0.2, "output": 10},
        "jev": {"input": 0.042, "output": 0},
    }
    costs = cost_estimates(
        {"input_tokens": 1000, "cached_input_tokens": 200, "output_tokens": 10},
        {"input_tokens": 1000, "output_tokens": 100},
        rates,
    )
    assert costs["cold_api_equivalent_usd"] == pytest.approx(0.002142)
    assert costs["cache_adjusted_api_equivalent_usd"] == pytest.approx(0.001782)
    assert costs["actual_billed_usd"] is None
    assert (
        cost_estimates(
            {"input_tokens": 1000, "cached_input_tokens": 200, "output_tokens": 10},
            {"input_tokens": 1000, "output_tokens": 100},
            rates,
            usage_complete=False,
        )["cold_api_equivalent_usd"]
        is None
    )


def test_rate_snapshot_requires_sources_date_and_finite_nonnegative_rates(tmp_path):
    path = tmp_path / "rates.json"
    data = {
        "date_verified": "2026-10-04",
        "unit": "USD per million tokens",
        "sources": ["https://example.org/pricing"],
        "main": {"fixture": {"input": 2, "cached_input": 0.2, "output": 10}},
        "jev": {"input": 0.042, "output": 0},
    }
    path.write_text(json.dumps(data))
    assert load_rate_snapshot(path, ["fixture"])["main"] == data["main"]
    data["main"]["fixture"]["input"] = -1
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_rate_snapshot(path, ["fixture"])
