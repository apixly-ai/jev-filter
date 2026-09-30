"""Survey: input reading, screening, aggregation and reporting without a paid API."""

import json

import pytest

from benchmarks.survey_data import SPEC, generate, score
from jev_context import survey


def fake_evaluate(truth):
    """Answer every question from the generated truth, with a controllable uncertain record."""

    def evaluate(records, task, questions, context, workers, model, batch_size="auto"):
        out = {}
        for r in records:
            t = truth[r["id"]]
            answers = {}
            for name, q in questions.items():
                if name == "screen":
                    answers[name] = {"type": "noul", "noul": 0.02 if t["spam"] else 0.97}
                elif name == "topic":
                    answers[name] = {
                        "type": "choice",
                        "choice": t["topic"],
                        "confidence": 0.95,
                        "probabilities": {k: float(k == t["topic"]) for k in q["criteria"]},
                    }
                elif name == "sentiment":
                    answers[name] = {
                        "type": "score",
                        "score": float(t["sentiment"]),
                        "confidence": 0.9,
                        "legend": {},
                        "probabilities": {},
                    }
                else:
                    answers[name] = {"type": "noul", "noul": 0.9 if t["churn"] else 0.05}
            out[r["id"]] = {"status": "OK", "answers": answers}
        return out, {
            "usage": {"input_tokens": 10 * len(records), "output_tokens": len(records)},
            "usage_complete": True,
            "requests": 1,
        }

    return evaluate


def write_dataset(tmp_path, n=120):
    records = generate(n)
    path = tmp_path / "records.jsonl"
    path.write_text(
        "\n".join(json.dumps({k: v for k, v in r.items() if k != "truth"}) for r in records),
        encoding="utf-8",
    )
    (tmp_path / "spec.json").write_text(json.dumps(SPEC), encoding="utf-8")
    return records


def test_reads_jsonl_csv_json_and_text_directories(tmp_path):
    (tmp_path / "a.jsonl").write_text(
        '{"id":"x","text":"hello","team":"A"}\n{bad json}\n', encoding="utf-8"
    )
    (tmp_path / "b.csv").write_text("id,body,team\ny,hi there,B\n", encoding="utf-8")
    (tmp_path / "c.json").write_text('[{"text":"arr","team":"C"}]', encoding="utf-8")
    (tmp_path / "d.txt").write_text("plain file " * 10, encoding="utf-8")
    records, meta = survey.read_inputs(
        [str(tmp_path)], text_field="text", keep=["team"], max_chars=50
    )
    by_id = {r["id"]: r for r in records}
    assert by_id["x"]["team"] == "A" and meta["parse_errors"] == 1
    assert "hi there" in by_id["y"]["text"]  # no 'text' column: row serialized as JSON
    assert by_id["d.txt"]["text_truncated"] is True and meta["truncated_texts"] == 1
    assert meta["files"] == 4


def test_record_cap_is_reported_not_silent(tmp_path):
    (tmp_path / "a.jsonl").write_text(
        "\n".join(json.dumps({"text": str(i)}) for i in range(10)), encoding="utf-8"
    )
    records, meta = survey.read_inputs([str(tmp_path / "a.jsonl")], max_records=4)
    assert len(records) == 4 and meta["truncated"] is True


def test_spec_validation_rejects_bad_group_by():
    with pytest.raises(ValueError, match="group_by"):
        survey.validate_spec({"questions": SPEC["questions"], "group_by": ["nope"]}, keep=[])
    with pytest.raises(ValueError, match="choice"):
        survey.validate_spec({"questions": SPEC["questions"], "group_by": ["sentiment"]}, keep=[])


def test_end_to_end_with_screening_and_crosstabs(tmp_path, monkeypatch, capsys):
    records = write_dataset(tmp_path)
    truth = {r["id"]: r["truth"] for r in records}
    monkeypatch.setattr(survey, "evaluate", fake_evaluate(truth))
    code = survey.main(
        ["--input", str(tmp_path / "records.jsonl"), "--spec", str(tmp_path / "spec.json")]
    )
    report = json.loads(capsys.readouterr().out)
    spam = sum(t["spam"] for t in truth.values())
    assert code == 0 and report["complete"] and report["screened_out"] == spam
    assert report["evaluated"] == len(records) - spam
    assert sum(report["questions"]["topic"]["counts"].values()) == report["evaluated"]
    assert set(report["crosstabs"]) == {"topic", "product"}
    reps = report["representatives"]["topic"]
    assert all(len(v) <= 2 for v in reps.values())
    total_excerpt = sum(
        len(e["excerpt"]) for g in report["representatives"].values() for v in g.values() for e in v
    )
    assert total_excerpt <= 4000
    archive = json.loads(open(report["archive"], encoding="utf-8").read())
    accuracy = score(records, archive["answers"])
    assert accuracy["topic"]["accuracy"] == 1.0 and accuracy["screen"]["accuracy"] == 1.0


def test_markdown_report_and_uncertain_accounting(tmp_path, monkeypatch, capsys):
    records = write_dataset(tmp_path, 40)
    truth = {r["id"]: r["truth"] for r in records}
    base = fake_evaluate(truth)

    def shaky(records, task, questions, context, workers, model, batch_size="auto"):
        out, stats = base(records, task, questions, context, workers, model, batch_size)
        first = next((rid for rid, e in out.items() if "topic" in e["answers"]), None)
        if first:
            out[first]["answers"]["topic"]["confidence"] = 0.3
        return out, stats

    monkeypatch.setattr(survey, "evaluate", shaky)
    survey.main(
        [
            "--input",
            str(tmp_path / "records.jsonl"),
            "--spec",
            str(tmp_path / "spec.json"),
            "--format",
            "md",
        ]
    )
    text = capsys.readouterr().out
    assert text.startswith("# Survey:") and "| option | count | share |" in text
    assert "Uncertain answers: 1" in text


def test_failed_records_make_the_report_incomplete(tmp_path, monkeypatch, capsys):
    records = write_dataset(tmp_path, 30)
    truth = {r["id"]: r["truth"] for r in records}
    base = fake_evaluate(truth)

    def partial(records, task, questions, context, workers, model, batch_size="auto"):
        out, stats = base(records, task, questions, context, workers, model, batch_size)
        if "topic" in questions:
            out[next(iter(out))] = {"status": "UNAVAILABLE", "answers": {}}
        return out, {**stats, "usage_complete": False}

    monkeypatch.setattr(survey, "evaluate", partial)
    code = survey.main(
        ["--input", str(tmp_path / "records.jsonl"), "--spec", str(tmp_path / "spec.json")]
    )
    report = json.loads(capsys.readouterr().out)
    assert (
        code == 2
        and report["failed"] == 1
        and not report["complete"]
        and not report["usage_complete"]
    )


def test_category_proposal_uses_a_fixed_sample_and_adds_other():
    records = [{"id": str(i), "text": f"record {i}"} for i in range(100)]
    seen = {}

    def helper(context):
        seen["records"] = context["records"]
        return json.dumps({"billing": "money", "bugs": "broken"}), {"model": "stub"}

    criteria, meta = survey.propose_categories(
        records, {"instructions": "topic"}, "t", helper, sample_size=10
    )
    assert set(criteria) == {"billing", "bugs", "other"} and meta["sample"] == 10
    again = {}
    survey.propose_categories(
        records,
        {"instructions": "topic"},
        "t",
        lambda c: (again.setdefault("r", c["records"]) and json.dumps({"a": 1, "b": 2}), {}),
        sample_size=10,
    )
    assert again["r"] == seen["records"]  # deterministic sample


def test_preflight_refuses_over_budget_and_dry_run_estimates(tmp_path, capsys):
    write_dataset(tmp_path, 60)
    args = ["--input", str(tmp_path / "records.jsonl"), "--spec", str(tmp_path / "spec.json")]
    assert survey.main(args + ["--dry-run"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["requests"] >= 2 and plan["input_tokens_estimate"] > 0
    assert plan["input_usd_estimate"] > 0
    assert survey.main(args + ["--max-usd", "0.000001"]) == 2
    refused = json.loads(capsys.readouterr().out)
    assert refused["refused"] == "budget" and not refused["ok"]
    assert survey.main(args + ["--max-usd", "0", "--max-requests", "1"]) == 2


def test_labels_produce_accuracy_reliability_and_a_floor(tmp_path, monkeypatch, capsys):
    records = write_dataset(tmp_path, 200)
    truth = {r["id"]: r["truth"] for r in records}
    monkeypatch.setattr(survey, "evaluate", fake_evaluate(truth))
    labels = tmp_path / "labels.jsonl"
    rows = [
        json.dumps({"id": rid, "topic": t["topic"], "churn": t["churn"]})
        for rid, t in truth.items()
        if not t["spam"]
    ]
    labels.write_text("\n".join(rows), encoding="utf-8")
    spec = str(tmp_path / "spec.json")
    survey.main(
        ["--input", str(tmp_path / "records.jsonl"), "--spec", spec, "--labels", str(labels)]
    )
    report = json.loads(capsys.readouterr().out)
    assert report["calibrated"] is True
    topic = report["calibration"]["topic"]
    assert topic["accuracy"] == 1.0 and topic["suggested_confidence_floor"] == 0.5
    assert "0.9-1.0" in topic["by_confidence"]
    assert report["calibration"]["churn"]["accuracy"] == 1.0


def test_unlabelled_reports_say_uncalibrated(tmp_path, monkeypatch, capsys):
    records = write_dataset(tmp_path, 30)
    monkeypatch.setattr(survey, "evaluate", fake_evaluate({r["id"]: r["truth"] for r in records}))
    survey.main(["--input", str(tmp_path / "records.jsonl"), "--spec", str(tmp_path / "spec.json")])
    report = json.loads(capsys.readouterr().out)
    assert report["calibrated"] is False and "uncalibrated" in report["calibration_note"]
