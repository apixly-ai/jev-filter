"""Optional LLM benchmark accounting must preserve unknown attempts."""

from benchmarks.providers import benchmark, normalize_adapter


def test_adapter_preserves_total_usage_and_ignores_last_attempt_only():
    result = normalize_adapter(
        {
            "model": "fixture-llm",
            "answers": {"x": {"type": "noul", "noul": 0.9}},
            "usage": {
                "input_tokens": 10,
                "output_tokens": 3,
                "input_tokens_total": 30,
                "output_tokens_total": 9,
                "n_retries": 2,
            },
        }
    )
    assert result["usage"] == {"input_tokens": 30, "output_tokens": 9}
    assert result["attempts"] == 3
    assert result["usage_complete"] is True


def test_adapter_unknown_totals_never_become_zero():
    result = normalize_adapter(
        {
            "model": "fixture",
            "answers": {},
            "usage": {
                "input_tokens": 10,
                "input_tokens_total": None,
                "output_tokens_total": 0,
                "n_retries": 1,
            },
        }
    )
    assert result["usage"]["input_tokens"] is None
    assert result["usage"]["output_tokens"] == 0
    assert result["usage_complete"] is False


def test_failed_live_arm_does_not_claim_actual_usage_available(monkeypatch):
    def unavailable(*_args):
        raise RuntimeError("synthetic provider failure")

    monkeypatch.setattr("benchmarks.providers.run", unavailable)
    report = benchmark("jev", "fixture", records=8, repeats=1, live=True)
    assert report["actual_usage_available"] is False
    assert report["runs"][0]["usage_complete"] is False
