import json

import pytest

from benchmarks import selection_speed


def test_shared_inputs_preserve_both_atomic_predicates_without_gold():
    records, gold = selection_speed.fixture(96)
    prompt = selection_speed.primary_prompt(records)
    assert all(
        requirement["statement"] in prompt for requirement in selection_speed.SPEC["requirements"]
    )
    assert all(record["text"] in prompt for record in records)
    assert "expected_ids" not in prompt
    assert "gold" not in prompt
    assert len(gold) == 48
    assert selection_speed.encoded_bytes(records) > len(selection_speed.encoded(records))


def test_score_rejects_duplicates_inventions_and_reviews_even_with_correct_set():
    good = {"selected_ids": ["a"], "needs_review": False}
    assert selection_speed.score(good, ["a", "b"], ["a"])["complete_correct"]
    duplicate = {"selected_ids": ["a", "a"], "needs_review": False}
    assert not selection_speed.score(duplicate, ["a", "b"], ["a"])["complete_correct"]
    invented = {"selected_ids": ["a", "invented"], "needs_review": False}
    assert selection_speed.score(invented, ["a", "b"], ["a"])["invalid_ids"] == ["invented"]
    review = {"selected_ids": ["a"], "needs_review": True}
    result = selection_speed.score(review, ["a", "b"], ["a"])
    assert result["id_set_correct"]
    assert not result["complete_correct"]
    assert result["needs_review"]


def test_false_negatives_are_visible_when_answer_is_partial_or_failed():
    result = selection_speed.score(
        {"selected_ids": ["b"], "needs_review": False}, ["a", "b"], ["a"]
    )
    assert result["false_positive_ids"] == ["b"]
    assert result["false_negative_ids"] == ["a"]
    failed = selection_speed.score(None, ["a", "b"], ["a"])
    assert failed["false_negative_ids"] == ["a"]
    assert failed["needs_review"]
    assert failed["answer_valid"] is False


def test_primary_tools_invalidate_answer_but_preserve_actual_usage():
    lines = [
        {"type": "item.started", "item": {"id": "tool-1", "type": "command_execution"}},
        {
            "type": "item.completed",
            "item": {
                "type": "agent_message",
                "text": '{"selected_ids":["a"],"needs_review":false}',
            },
        },
        {
            "type": "turn.completed",
            "usage": {"input_tokens": 12, "cached_input_tokens": 4, "output_tokens": 3},
        },
    ]
    parsed = selection_speed.primary_receipt([json.dumps(line) for line in lines])
    assert parsed["answer"] is None
    assert parsed["tool_items"] == 1
    assert parsed["usage_complete"]
    assert parsed["known_usage"]["input_tokens"] == 12
    assert not selection_speed.score(parsed["answer"], ["a"], ["a"])["complete_correct"]


def test_missing_usage_remains_unknown_and_excluded_from_speed_success():
    parsed = selection_speed.primary_receipt(
        [json.dumps({"type": "turn.completed", "usage": {"input_tokens": 9}})]
    )
    assert not parsed["usage_complete"]
    assert parsed["usage"]["output_tokens"] is None
    assert parsed["known_usage"]["input_tokens"] == 9


def test_summary_keeps_incorrect_and_timeout_runs_in_denominator():
    rows = [
        {
            "arm": "jev",
            "elapsed_ms": 100,
            "complete_correct": True,
            "needs_review": False,
            "timeout": False,
            "usage_complete": True,
        },
        {
            "arm": "jev",
            "elapsed_ms": 200,
            "complete_correct": False,
            "needs_review": True,
            "timeout": True,
            "usage_complete": False,
        },
        {
            "arm": "primary",
            "elapsed_ms": 1000,
            "complete_correct": True,
            "needs_review": False,
            "timeout": False,
            "usage_complete": True,
        },
    ]
    result = selection_speed.summarize(rows)
    assert result["jev"]["runs"] == 2
    assert result["jev"]["complete_correct_runs"] == 1
    assert result["jev"]["median_ms"] == 150
    assert result["jev"]["timeout_runs"] == 1
    assert result["jev"]["usage_complete"] is False


def test_jev_captures_transport_roundtrip_without_calling_it_native_inference(monkeypatch):
    stats = {
        "elapsed_ms": 124,
        "requests": 1,
        "workers": 1,
        "usage": {"input_tokens": 12, "output_tokens": 3},
        "usage_complete": True,
    }
    monkeypatch.setattr(
        selection_speed.pool,
        "run",
        lambda *args, **kwargs: {
            "results": [{"model": "resolved", "latency_ms": 123}],
            **stats,
        },
    )

    def evaluate(*args, **kwargs):
        selection_speed.pool.run([])
        return {}, stats

    monkeypatch.setattr(selection_speed.analysis, "evaluate", evaluate)
    monkeypatch.setattr(
        selection_speed.analysis,
        "summarize",
        lambda *args: {"selected_ids": ["r000"], "review_ids": [], "complete": True},
    )
    records, gold = selection_speed.fixture(1)
    result = selection_speed.jev_run(records, gold, 12)
    assert result["provider_request_elapsed_ms"] == [123]
    assert result["native_provider_inference_ms"] is None
    assert result["observed_models"] == ["resolved"]
    assert result["complete_correct"]


def test_harness_failure_preserves_unavailable_usage_without_exception_text():
    records, gold = selection_speed.fixture(2)
    failure = selection_speed.failure_row("jev", records, gold, RuntimeError("private trace"))
    assert failure["usage_complete"] is False
    assert failure["usage"] is None
    assert failure["known_usage"] is None
    assert failure["unknown_usage_attempts"] is None
    assert failure["failed_requests"] is None
    assert failure["false_negative_ids"] == gold
    assert "private trace" not in json.dumps(failure)


@pytest.mark.parametrize("repetition", [0, 1, 2])
def test_run_order_rotates_three_arms(repetition):
    arms = ["jev", "gpt-5.6-luna", "gpt-6-astra"]
    assert selection_speed.run_order(arms, repetition) == arms[repetition:] + arms[:repetition]
