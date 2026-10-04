from unittest.mock import patch

from benchmarks.decision_contracts import _worker


def test_core_ab_uses_no_provider_and_checks_failure_bookkeeping():
    with patch("jev_context.provider.Client.call", side_effect=AssertionError("offline only")):
        result = _worker("treatment")
    assert result["correct"] == result["case_count"] == 13
    assert result["false_actions"] == result["unsafe_automatic_decisions"] == 0
    failures = [r for r in result["cases"] if "failure" in r["id"]]
    assert len(failures) == 4
    assert all(r["bookkeeping_preserved"] for r in failures)
    assert result["actual_model_usage"]["requests"] == 0
