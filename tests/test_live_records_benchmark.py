import json

from benchmarks import live_records


def test_quality_keeps_reviewed_positives_in_recall_denominator():
    result = live_records.quality(
        {"positive": "REVIEW", "negative": "EXCLUDE", "wrong": "MATCH"},
        {"positive": "MATCH", "negative": "EXCLUDE", "wrong": "EXCLUDE"},
    )
    assert result["recall"] == 0
    assert result["false_negative_ids"] == ["positive"]
    assert result["false_positive_ids"] == ["wrong"]
    assert result["review_ids"] == ["positive"]
    assert result["automatic_error_rate"] == 0.5


def test_model_accounting_preserves_unknown_and_partial_failures():
    rows = [
        {
            "id": "0",
            "ok": True,
            "model": "resolved-model",
            "usage": {"input_tokens": 17, "output_tokens": 3},
            "usage_complete": True,
        },
        {"id": "1", "ok": False, "error_type": "ProviderError"},
    ]
    result = live_records.model_accounting(rows)
    assert result["observed_models"] == ["resolved-model"]
    assert result["usage_complete"] is False
    assert result["known_usage"] == {"input_tokens": 17, "output_tokens": 3}
    assert result["failed_request_ids"] == ["1"]
    assert result["by_model"][0]["usage_complete"] is True


def test_model_accounting_unknown_success_tokens_are_never_counted_as_zero():
    result = live_records.model_accounting(
        [{"id": "0", "ok": True, "model": "resolved", "usage": {"input_tokens": 4}}]
    )
    assert result["usage_complete"] is False
    assert result["by_model"][0]["known_usage"] == {"input_tokens": 4, "output_tokens": None}


def answer(probabilities, selected):
    return {
        "type": "choice",
        "choice": selected,
        "probabilities": probabilities,
        "confidence": 0.1,
    }


def test_threshold_selection_uses_calibration_only():
    calibration = [
        {
            "id": "cal-a",
            "expected": "MATCH",
            "answer": answer(
                {"SUPPORTED": 0.9, "CONTRADICTED": 0.05, "UNKNOWN": 0.05}, "SUPPORTED"
            ),
        },
        {
            "id": "cal-b",
            "expected": "EXCLUDE",
            "answer": answer({"SUPPORTED": 0.6, "CONTRADICTED": 0.3, "UNKNOWN": 0.1}, "SUPPORTED"),
        },
    ]
    chosen = live_records.select_policy(calibration, thresholds=[0, 0.55, 0.7, 0.95])
    assert chosen["threshold"] == 0.7
    assert chosen["selection_source"] == "calibration_only"
    assert chosen["metrics"]["review_ids"] == ["cal-b"]


def test_threshold_selection_all_reviews_when_no_safe_automatic_candidate():
    calibration = [
        {
            "id": "cal-a",
            "expected": "EXCLUDE",
            "answer": answer({"SUPPORTED": 1.0, "CONTRADICTED": 0.0, "UNKNOWN": 0.0}, "SUPPORTED"),
        }
    ]
    chosen = live_records.select_policy(calibration, thresholds=[0, 0.7, 0.95])
    assert chosen["threshold"] is None
    assert chosen["status"] == "all_review_no_eligible_threshold"


def test_fixed_fixtures_have_separated_groups_and_independent_diff_labels():
    records = live_records.uncertainty_fixture()
    calibration = {r["group"] for r in records if r["split"] == "calibration"}
    holdout = {r["group"] for r in records if r["split"] == "holdout"}
    assert not calibration.intersection(holdout)
    assert {r["expected"] for r in records} == {"MATCH", "EXCLUDE", "REVIEW"}
    assert set(live_records.DIFF_EXPECTED) == set(live_records.DIFF_FILES)


def test_operation_measures_real_pipeline_without_leaking_gold_or_source(monkeypatch):
    requests = []

    def fake_run(items, **kwargs):
        assert kwargs["workers"] <= 4
        requests.extend(items)
        return {
            "ok": True,
            "results": [
                {
                    "id": item["id"],
                    "ok": True,
                    "model": "actual-resolved-model",
                    "answers": {
                        key: answer({"RELEVANT": 0.9, "OTHER": 0.05, "REVIEW": 0.05}, "RELEVANT")
                        for key in item["request"]["questions"]
                    },
                    "usage": {"input_tokens": 20, "output_tokens": 7},
                    "usage_complete": True,
                }
                for item in items
            ],
            "usage": {"input_tokens": 20, "output_tokens": 7},
            "usage_complete": True,
            "unknown_usage_attempts": 0,
        }

    monkeypatch.setattr(live_records.pool, "run", fake_run)
    packet = live_records.operation(
        lambda: (
            [
                {
                    "id": "record-a",
                    "text": "UNIQUE_SYNTHETIC_SOURCE_BODY",
                    "path": "/synthetic/runtime-root/input.py",
                }
            ],
            {"ok": True},
        ),
        "Find supporting evidence",
        None,
        {"record-a": "MATCH"},
    )
    assert packet["quality"]["exact"]
    assert packet["model_accounting"]["observed_models"] == ["actual-resolved-model"]
    assert packet["model_accounting"]["known_usage"] == {"input_tokens": 20, "output_tokens": 7}
    assert packet["whole_operation_ms"] >= packet["collection_ms"]
    assert "UNIQUE_SYNTHETIC_SOURCE_BODY" not in json.dumps(packet)
    assert "expected" not in json.dumps(requests)
    assert "/synthetic/runtime-root" not in json.dumps(requests)
    assert "input.py" in json.dumps(requests)
