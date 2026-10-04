"""Offline uncertainty and versioned analysis contracts; no model calls."""

import json
from pathlib import Path
from unittest.mock import patch

import jsonschema
import pytest

from jev_context import analysis


def native_choice(selected="SUPPORTED", probabilities=None):
    return {
        "type": "choice",
        "choice": selected,
        "confidence": 0.04,
        "probabilities": probabilities
        or {"SUPPORTED": 0.36, "CONTRADICTED": 0.33, "UNKNOWN": 0.31},
    }


def policy():
    return {"min_top_probability": 0.55, "min_margin": 0.10}


def test_uncertain_requirement_remains_reviewable_with_native_distribution():
    spec = analysis.validate(
        {
            "requirements": [{"id": "current", "statement": "Is current", "expected": True}],
            "uncertainty": policy(),
        }
    )
    entry = {"status": "OK", "answers": {"current": native_choice()}}
    assert analysis.decision(entry, spec) == "REVIEW"
    summary = analysis.summarize(
        [{"id": "p", "source_id": "s", "text": "Uncertain evidence", "source": {}}],
        {"p": entry},
        spec,
    )
    assert summary["review_reasons"]["s"][0]["question"] == "current"
    assert summary["review_reasons"]["s"][0]["reason"] == "below_min_top_probability"
    assert entry["answers"]["current"]["probabilities"]["SUPPORTED"] == 0.36


def test_uncertain_filter_never_excludes_a_record():
    spec = analysis.validate({"uncertainty": policy()})
    answer = native_choice("OTHER", {"OTHER": 0.51, "RELEVANT": 0.49, "REVIEW": 0})
    assert analysis.decision({"status": "OK", "answers": {"relevance": answer}}, spec) == "REVIEW"


def test_per_question_thresholds_and_missing_metrics():
    from jev_context.decision_policy import assess, validate

    configured = validate(
        {"min_top_probability": 0.8, "questions": {"target": {"min_top_probability": 0.3}}},
        questions={"target"},
    )
    assert not assess(native_choice(), "target", configured)
    assert (
        assess({"type": "choice", "choice": "SUPPORTED"}, "target", configured)[0]["reason"]
        == "missing_top_probability"
    )
    with pytest.raises(ValueError, match="known question"):
        validate({"questions": {"typo": {"min_margin": 0.1}}}, questions={"target"})


def test_enabled_policy_does_not_admit_a_forced_nonwinning_choice():
    from jev_context.decision_policy import assess, validate

    answer = native_choice("CLICK", {"BLOCKED": 0.45, "CLICK": 0.35, "DONE": 0.20})
    configured = validate({"min_top_probability": 0.4, "min_margin": 0.05})
    assert assess(answer, "operation", configured)[0]["reason"] == "selected_option_not_top"
    assert not assess(answer, "operation", validate({}))


@pytest.mark.parametrize("bad", [True, -0.1, 1.1, float("nan"), "0.5"])
def test_thresholds_reject_nonfinite_or_non_numeric_values(bad):
    with pytest.raises(ValueError, match="min_margin"):
        analysis.validate({"uncertainty": {"min_margin": bad}})


def test_uncertain_choose_reviews_all_candidates_without_guessing():
    parts = [{"id": "p", "source_id": "s", "text": "candidate", "source": {}}]
    selection = native_choice("c0", {"c0": 0.51, "NONE": 0.49, "REVIEW": 0})
    response = {
        "ok": True,
        "results": [{"id": "choose", "ok": True, "answers": {"target": selection}}],
        "usage_complete": True,
    }
    with patch("jev_context.pool.run", return_value=response):
        judgments, stats = analysis.evaluate(
            parts, "Choose one", spec={"mode": "choose", "uncertainty": policy()}
        )
    assert judgments["p"]["decision"] == "REVIEW"
    assert judgments["p"]["status"] == "UNCERTAIN"
    assert stats["selection"] == selection
    assert stats["selection_review_reasons"][0]["question"] == "target"


def test_contract_fingerprint_tracks_semantics_and_not_presentation():
    spec = analysis.validate({"contract": {"id": "current-records", "version": "1.0.0"}})
    base = analysis.contract_metadata(spec)
    assert base["id"] == "current-records"
    assert base["version"] == "1.0.0"
    assert len(base["fingerprint"]) == 64
    displayed = analysis.validate({**spec, "format": "text", "batch_size": 1})
    assert analysis.contract_metadata(displayed) == base
    changed = analysis.validate({**spec, "uncertainty": policy()})
    assert analysis.contract_metadata(changed)["fingerprint"] != base["fingerprint"]
    pinned = {**spec, "contract": {**spec["contract"], "fingerprint": base["fingerprint"]}}
    assert analysis.contract_metadata(analysis.validate(pinned)) == base
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        analysis.validate({**pinned, "uncertainty": policy()})


def test_contract_is_visible_on_missing_context_admission_and_matches_schema():
    spec = {
        "contract": {"id": "records", "version": "1"},
        "required_context": ["scope"],
        "uncertainty": {**policy(), "questions": {"relevance": {"min_confidence": 0.2}}},
    }
    jsonschema.validate(spec, json.loads(Path("schemas/analysis.schema.json").read_text()))
    validated = analysis.validate(spec)
    assert analysis.context_admission(validated)["contract"]["id"] == "records"
