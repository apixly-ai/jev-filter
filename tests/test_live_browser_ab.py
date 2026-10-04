"""Offline accounting and verification contracts for the opt-in live browser A/B."""

from benchmarks.live_browser_ab import classify_outcome, summarize_calls


def test_done_without_independent_state_is_a_false_completion():
    outcome = classify_outcome("done", "done", False, 0)
    assert outcome == {
        "passed": False,
        "correct_completion": False,
        "correct_gate": False,
        "review_or_failure": True,
        "false_completion": True,
        "wrong_actions": 0,
    }


def test_expected_confirmation_must_preserve_state_and_gate():
    assert classify_outcome("needs_confirmation", "needs_confirmation", True, 0)["correct_gate"]
    assert not classify_outcome("needs_confirmation", "needs_confirmation", True, 1)["passed"]


def test_unknown_call_usage_preserves_known_lower_bound_and_unknown_cost():
    summary = summarize_calls(
        [
            {
                "model": "jev-2",
                "request_bytes": 123,
                "state_bytes": 50,
                "usage": {"input_tokens": 40, "output_tokens": 7},
                "usage_complete": True,
                "attempts": 1,
            },
            {
                "model": "jev-2",
                "request_bytes": 100,
                "state_bytes": 40,
                "error_type": "ProviderError",
                "unknown_usage_attempts": 1,
                "attempts": 1,
            },
        ]
    )
    assert summary["known_usage"] == {"input_tokens": 40, "output_tokens": 7}
    assert summary["usage_complete"] is False
    assert summary["unknown_usage_attempts"] == 1
    assert summary["estimated_input_usd"] is None
    assert summary["known_input_usd_lower_bound"] > 0
    assert summary["request_bytes"] == 223
    assert summary["state_bytes"] == 90
    assert summary["failed_provider_calls"] == 1


def test_retried_calls_are_counted_and_unknown_usage_remains_unknown():
    summary = summarize_calls(
        [
            {
                "model": "jev-2",
                "request_bytes": 90,
                "state_bytes": 50,
                "usage": {"input_tokens": 20, "output_tokens": 2},
                "usage_complete": False,
                "attempts": 3,
                "unknown_usage_attempts": 2,
            }
        ]
    )
    assert summary["provider_attempts"] == 3
    assert summary["provider_retries"] == 2
    assert summary["unknown_usage_attempts"] == 2
    assert summary["model_usage"]["jev-2"]["input_tokens"] == 20
