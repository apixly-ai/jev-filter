"""Held-out threshold evaluation uses saved synthetic judgments, never a provider."""

import copy
import json
from pathlib import Path

import pytest


def dataset():
    return {
        "version": 1,
        "model": "jev-1.13.0",
        "contract": {"id": "binary-evidence", "version": "1", "fingerprint": "a" * 64},
        "records": [
            {
                "id": "c1",
                "group": "cal-a",
                "split": "calibration",
                "label": True,
                "probability": 0.9,
            },
            {
                "id": "c2",
                "group": "cal-b",
                "split": "calibration",
                "label": False,
                "probability": 0.1,
            },
            {
                "id": "c3",
                "group": "cal-c",
                "split": "calibration",
                "label": False,
                "probability": 0.6,
            },
            {"id": "h1", "group": "test-a", "split": "holdout", "label": True, "probability": 0.8},
            {"id": "h2", "group": "test-b", "split": "holdout", "label": False, "probability": 0.2},
            {"id": "h3", "group": "test-c", "split": "holdout", "label": True, "status": "failed"},
        ],
    }


def test_threshold_selection_never_reads_holdout_labels_or_probabilities():
    from jev_context.evaluation import evaluate

    original = dataset()
    changed = copy.deepcopy(original)
    for row in changed["records"]:
        if row["split"] == "holdout":
            row["label"] = not row["label"]
            row["probability"] = 0.51
    first = evaluate(original, thresholds=[0.5, 0.7, 0.9], max_error_rate=0)
    second = evaluate(changed, thresholds=[0.5, 0.7, 0.9], max_error_rate=0)
    assert first["selection"] == second["selection"]
    assert first["selection"]["threshold"] == 0.7
    assert first["holdout"]["coverage"] == pytest.approx(2 / 3)
    assert first["holdout"]["recall"] == 0.5  # Failed positives are retained in the denominator.
    assert first["holdout"]["failed"] == 1
    assert first["holdout"]["brier"] == pytest.approx(0.04)
    assert first["holdout"]["ece"] == pytest.approx(0.2)


def test_group_leakage_and_mixed_model_or_contract_are_rejected():
    from jev_context.evaluation import evaluate

    leaked = dataset()
    leaked["records"][3]["group"] = "cal-a"
    with pytest.raises(ValueError, match="both splits"):
        evaluate(leaked)
    for field, value in [("model", "other-model"), ("contract_fingerprint", "b" * 64)]:
        mixed = dataset()
        mixed["records"][0][field] = value
        with pytest.raises(ValueError, match="mixed"):
            evaluate(mixed)


def test_native_answers_and_missing_probabilities_preserve_review_rows():
    from jev_context.evaluation import evaluate

    payload = dataset()
    payload["positive_label"] = "SUPPORTED"
    row = payload["records"][3]
    del row["probability"]
    row["answer"] = {
        "type": "choice",
        "choice": "SUPPORTED",
        "confidence": 0.6,
        "probabilities": {"SUPPORTED": 0.8, "CONTRADICTED": 0.2},
    }
    payload["records"][4].pop("probability")
    payload["records"][4]["status"] = "review"
    report = evaluate(payload, thresholds=[0.7])
    assert report["dispositions"][-2]["decision"] == "REVIEW"
    assert report["dispositions"][-2]["reason"] == "source_review"
    assert report["source_inference_usage"]["usage_complete"] is False
    assert report["evaluation_usage"]["requests"] == 0
    assert report["contract"] == payload["contract"]
    assert report["method"] == "held_out_threshold_evaluation"


def test_reliability_metrics_include_known_probabilities_on_review_rows():
    from jev_context.evaluation import evaluate

    payload = dataset()
    payload["records"][4].update(status="review", probability=0.8, label=False)
    report = evaluate(payload, thresholds=[0.7])
    assert report["holdout"]["probability_records"] == 2
    assert report["holdout"]["brier"] == pytest.approx((0.04 + 0.64) / 2)
    assert report["dispositions"][4]["decision"] == "REVIEW"
    assert report["holdout"]["coverage"] == pytest.approx(1 / 3)


def test_positive_unknown_attempt_count_cannot_be_reported_as_complete_usage():
    from jev_context.evaluation import evaluate

    payload = dataset()
    payload["usage"] = {
        "usage": {"input_tokens": 100, "output_tokens": 10},
        "usage_complete": True,
        "unknown_usage_attempts": 1,
    }
    source_usage = evaluate(payload)["source_inference_usage"]
    assert source_usage["usage_complete"] is False
    assert source_usage["input_tokens"] == 100 and source_usage["output_tokens"] == 10
    assert source_usage["unknown_usage_attempts"] == 1


def test_eval_cli_writes_reproducible_report_without_raw_evidence(tmp_path, capsys):
    from jev_context.evaluation import main

    source = tmp_path / "source.json"
    output = tmp_path / "report.json"
    payload = dataset()
    payload["records"][0]["text"] = "PRIVATE SOURCE EVIDENCE"
    source.write_text(json.dumps(payload))
    assert main(["--input", str(source), "--output", str(output), "--threshold", ".7"]) == 0
    report = json.loads(output.read_text())
    assert len(report["input_sha256"]) == 64
    assert "PRIVATE SOURCE EVIDENCE" not in output.read_text()
    assert json.loads(capsys.readouterr().out)["output"] == str(output.resolve())
    assert Path(report["output"]) == output.resolve()


@pytest.mark.parametrize("bad", [False, -0.1, 1.1, float("nan"), "0.5"])
def test_invalid_probabilities_are_rejected(bad):
    from jev_context.evaluation import evaluate

    payload = dataset()
    payload["records"][0]["probability"] = bad
    with pytest.raises(ValueError, match="probability"):
        evaluate(payload)
