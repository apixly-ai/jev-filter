"""Survey: typed judgments over many records, aggregated by the program into an evidence report.

Jev answers bounded questions per record (choice / score / noul) in packed parallel requests.
Code does everything a decision model should not: counting, cross-tabulation, ranking,
uncertainty accounting and cost. Narrative synthesis is left to the caller's LLM, which reads
the compact report instead of the raw records. Optional steps:

* ``screen``: one cheap noul per record first; only records that pass get the full question set.
* ``--propose-categories``: an OpenAI-compatible text model proposes category names from a
  fixed-seed sample; Jev then classifies every record into them (plus ``other``).
"""

import argparse
import csv
import io
import json
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from . import analysis

MAX_RECORDS = 200_000
SUFFIXES = {".jsonl", ".ndjson", ".json", ".csv", ".txt", ".md"}


# -- input ------------------------------------------------------------------------------------
def _rows_from_text(name, raw):
    suffix = Path(name).suffix.lower()
    if suffix in (".jsonl", ".ndjson") or (
        suffix not in (".json", ".csv") and raw.lstrip().startswith("{") and "\n{" in raw
    ):
        for n, line in enumerate(raw.splitlines(), 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    yield {"_parse_error": True, "_line": n}
        return
    if suffix == ".json" or raw.lstrip().startswith(("[", "{")):
        data = json.loads(raw)
        if isinstance(data, dict):
            data = data.get("records", [data])
        yield from data
        return
    if suffix == ".csv":
        yield from csv.DictReader(io.StringIO(raw.lstrip("﻿")))
        return
    yield {"id": name, "text": raw}


def read_inputs(
    paths, text_field="text", id_field="id", keep=(), max_records=MAX_RECORDS, max_chars=4000
):
    """Records as {id, text, **kept metadata}; long texts are cut and flagged, never dropped."""
    records, meta = (
        [],
        {"files": 0, "rows": 0, "parse_errors": 0, "truncated_texts": 0, "truncated": False},
    )
    seen = set()

    def sources():
        for path in paths:
            if path == "-":
                yield "stdin.jsonl", sys.stdin.read()
                continue
            p = Path(path)
            if p.is_dir():
                for f in sorted(
                    x for x in p.rglob("*") if x.is_file() and x.suffix.lower() in SUFFIXES
                ):
                    yield str(f.relative_to(p)), f.read_text(encoding="utf-8", errors="replace")
            else:
                yield p.name, p.read_text(encoding="utf-8", errors="replace")

    for name, raw in sources():
        meta["files"] += 1
        for n, row in enumerate(_rows_from_text(name, raw), 1):
            meta["rows"] += 1
            if len(records) >= max_records:
                meta["truncated"] = True
                return records, meta
            if not isinstance(row, dict) or row.get("_parse_error"):
                meta["parse_errors"] += 1
                continue
            rid = str(row.get(id_field) or f"{name}#{n}")
            if rid in seen:
                rid = f"{rid}#{n}"
            seen.add(rid)
            text = row.get(text_field)
            if not isinstance(text, str):
                text = json.dumps(
                    {k: v for k, v in row.items() if k != id_field}, ensure_ascii=False
                )
            record = {"id": rid, "text": text}
            if len(text) > max_chars:
                record["text"] = text[:max_chars]
                record["text_truncated"] = True
                meta["truncated_texts"] += 1
            for k in keep:
                if k in row and k not in ("id", "text"):
                    record[k] = row[k]
            records.append(record)
    return records, meta


# -- spec -------------------------------------------------------------------------------------
def validate_spec(spec, keep):
    if (
        not isinstance(spec, dict)
        or not isinstance(spec.get("questions"), dict)
        or not spec["questions"]
    ):
        raise ValueError("survey spec needs questions")
    analysis.validate({"mode": "analyze", "questions": spec["questions"]})
    for name in spec.get("group_by", []):
        if name not in spec["questions"] and name not in keep:
            raise ValueError(f"group_by {name!r} must be a question id or a kept field")
        q = spec["questions"].get(name)
        if q and q["type"] != "choice":
            raise ValueError("group_by questions must be choice questions")
    screen = spec.get("screen")
    if screen is not None:
        if not isinstance(screen, dict) or "instructions" not in screen:
            raise ValueError("screen needs instructions")
    floor = spec.get("confidence_floor", 0.6)
    if not 0 <= floor <= 1:
        raise ValueError("confidence_floor must be in 0..1")
    return spec


# -- evaluation -------------------------------------------------------------------------------
def evaluate(records, task, questions, context, workers, model, batch_size="auto"):
    from .cli import chunks, normalize

    normalized = normalize([{k: v for k, v in r.items()} for r in records])
    parts = list(chunks(normalized))
    for part, record in zip(parts, normalized):
        part["source"] = {k: v for k, v in record.items() if k not in ("id", "text", "sha256")}
    spec = {
        "mode": "analyze",
        "questions": questions,
        "context": context or {},
        "model": model,
        "batch_size": batch_size,
    }
    judgments, stats = analysis.evaluate(parts, task, workers=workers, spec=spec)
    by_record = {}
    for part in parts:
        entry = judgments.get(part["id"], {"status": "MISSING", "answers": {}})
        by_record[part["source_id"]] = entry
    return by_record, stats


def is_uncertain(answer, floor):
    if answer["type"] == "noul":
        return abs(answer["noul"] - 0.5) < (1 - floor) / 2 + 0.05
    return answer.get("confidence", 1) < floor


def aggregate(records, answers, spec, budget_chars=4000):
    questions = spec["questions"]
    floor = spec.get("confidence_floor", 0.6)
    keep_groups = spec.get("group_by", [])
    by_id = {r["id"]: r for r in records}
    evaluated = [
        rid
        for rid, e in answers.items()
        if e.get("status") == "OK" and len(e["answers"]) == len(questions)
    ]
    failed = sorted(set(by_id) - set(evaluated))
    summary = {}
    uncertain_ids = set()
    for name, q in questions.items():
        values = [(rid, answers[rid]["answers"][name]) for rid in evaluated]
        unsure = [rid for rid, a in values if is_uncertain(a, floor)]
        uncertain_ids.update(unsure)
        block = {"type": q["type"], "answered": len(values), "uncertain": len(unsure)}
        if q["type"] == "choice":
            counts = Counter(a["choice"] for _, a in values)
            block["counts"] = {k: counts.get(k, 0) for k in q["criteria"]}
            block["share"] = {
                k: round(v / len(values), 4) if values else None for k, v in block["counts"].items()
            }
            block["mean_confidence"] = (
                round(sum(a["confidence"] for _, a in values) / len(values), 4) if values else None
            )
        elif q["type"] == "score":
            scores = [a["score"] for _, a in values]
            block["mean"] = round(sum(scores) / len(scores), 4) if scores else None
            levels = Counter(round(s) for s in scores)
            block["levels"] = {
                str(i): {
                    "label": lvl if isinstance(lvl, str) else json.dumps(lvl)[:80],
                    "count": levels.get(i, 0),
                }
                for i, lvl in enumerate(q["criteria"])
            }
        else:
            probs = [a["noul"] for _, a in values]
            block["yes"] = sum(p >= 0.5 for p in probs)
            block["yes_share"] = round(block["yes"] / len(probs), 4) if probs else None
            block["mean_probability"] = round(sum(probs) / len(probs), 4) if probs else None
        summary[name] = block

    def group_value(rid, name):
        if name in questions:
            return answers[rid]["answers"][name]["choice"]
        return str(by_id[rid].get(name, "∅"))

    crosstabs = {}
    for g in keep_groups:
        table = defaultdict(lambda: {"n": 0})
        for rid in evaluated:
            cell = table[group_value(rid, g)]
            cell["n"] += 1
            for name, q in questions.items():
                if name == g:
                    continue
                a = answers[rid]["answers"][name]
                if q["type"] == "choice":
                    cell.setdefault(name, Counter())[a["choice"]] += 1
                elif q["type"] == "score":
                    cell.setdefault(name + "_sum", 0.0)
                    cell[name + "_sum"] += a["score"]
                else:
                    cell.setdefault(name + "_yes", 0)
                    cell[name + "_yes"] += a["noul"] >= 0.5
        rendered = {}
        for key, cell in sorted(table.items(), key=lambda kv: -kv[1]["n"]):
            out = {"n": cell["n"]}
            for name, q in questions.items():
                if name == g:
                    continue
                if q["type"] == "choice":
                    out[name] = dict(cell.get(name, {}))
                elif q["type"] == "score":
                    out[name + "_mean"] = round(cell.get(name + "_sum", 0) / cell["n"], 4)
                else:
                    out[name + "_yes_share"] = round(cell.get(name + "_yes", 0) / cell["n"], 4)
            rendered[key] = out
        crosstabs[g] = rendered

    # Representatives: the most confident records per group, with bounded excerpts.
    representatives = {}
    per_group = spec.get("examples_per_group", 3)
    remaining = budget_chars
    for g in keep_groups or []:
        reps = {}
        buckets = defaultdict(list)
        for rid in evaluated:
            conf = answers[rid]["answers"][g]["confidence"] if g in questions else 1
            buckets[group_value(rid, g)].append((conf, rid))
        for key, items in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
            chosen = []
            for conf, rid in sorted(items, reverse=True)[:per_group]:
                excerpt = by_id[rid]["text"][: max(0, min(240, remaining))]
                remaining -= len(excerpt)
                chosen.append({"id": rid, "confidence": round(conf, 4), "excerpt": excerpt})
            reps[key] = chosen
        representatives[g] = reps
    return {
        "records": len(records),
        "evaluated": len(evaluated),
        "failed": len(failed),
        "failed_ids": failed[:50],
        "uncertain_records": len(uncertain_ids),
        "uncertain_ids": sorted(uncertain_ids)[:50],
        "questions": summary,
        "crosstabs": crosstabs,
        "representatives": representatives,
    }


def render_markdown(report):
    lines = [
        f"# Survey: {report['task']}",
        "",
        f"Records: {report['records']} · evaluated: {report['evaluated']} · failed: {report['failed']} · "
        f"uncertain: {report['uncertain_records']}",
        "",
    ]
    for name, block in report["questions"].items():
        lines.append(f"## {name} ({block['type']})")
        lines.append("")
        if block["type"] == "choice":
            lines += ["| option | count | share |", "|---|---:|---:|"]
            for k, v in sorted(block["counts"].items(), key=lambda kv: -kv[1]):
                share = block["share"][k]
                lines.append(
                    f"| {k} | {v} | {share:.1%} |" if share is not None else f"| {k} | {v} | – |"
                )
        elif block["type"] == "score":
            lines.append(f"Mean score: {block['mean']}")
            lines += ["", "| level | label | count |", "|---:|---|---:|"]
            for i, lvl in block["levels"].items():
                lines.append(f"| {i} | {lvl['label']} | {lvl['count']} |")
        else:
            lines.append(
                f"Yes: {block['yes']} ({(block['yes_share'] or 0):.1%}), mean probability {block['mean_probability']}"
            )
        lines.append(f"Uncertain answers: {block['uncertain']}")
        lines.append("")
    for g, table in report["crosstabs"].items():
        lines += [f"## By {g}", ""]
        for key, cell in table.items():
            lines.append(
                f"- **{key}** (n={cell['n']}): "
                + ", ".join(
                    f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in cell.items() if k != "n"
                )
            )
        lines.append("")
    return "\n".join(lines)


def propose_categories(records, question, task, helper, sample_size=60, seed=7, max_categories=12):
    """Ask a text model for category names from a fixed-seed sample; returns choice criteria."""
    rng = random.Random(seed)
    sample = rng.sample(records, min(sample_size, len(records)))
    context = {
        "task": task,
        "question": question.get("instructions"),
        "instructions": (
            f"Propose at most {max_categories} mutually exclusive categories that cover these records. "
            'Return JSON {"text": "<json object name -> one-line description>"}. '
            "Names are short snake_case; do not include an 'other' category."
        ),
        "records": [r["text"][:400] for r in sample],
    }
    raw, meta = helper(context)
    if raw is None:
        raise ValueError("text model declined to propose categories")
    try:
        categories = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("text model returned invalid categories") from None
    if not isinstance(categories, dict) or not 2 <= len(categories) <= max_categories:
        raise ValueError("text model returned an unusable category set")
    criteria = {str(k)[:40]: str(v)[:200] for k, v in categories.items()}
    criteria["other"] = "None of the other categories fits."
    return criteria, {"sample": len(sample), "seed": seed, **(meta or {})}


# -- CLI --------------------------------------------------------------------------------------
def main(argv=None):
    from .cli import save_archive
    from .stats import record

    parser = argparse.ArgumentParser(prog="jev-filter survey", description=__doc__)
    parser.add_argument(
        "--input", action="append", required=True, help="File, directory or - (repeatable)"
    )
    parser.add_argument(
        "--spec", required=True, help="Survey spec JSON (questions, group_by, screen, ...)"
    )
    parser.add_argument("--task", help="What the survey is for (overrides spec.task)")
    parser.add_argument("--text-field", default="text")
    parser.add_argument("--id-field", default="id")
    parser.add_argument(
        "--keep", action="append", default=[], help="Metadata field to keep (repeatable)"
    )
    parser.add_argument("--max-records", type=int, default=MAX_RECORDS)
    parser.add_argument("--max-chars", type=int, default=4000)
    parser.add_argument("--workers", default="auto")
    parser.add_argument("--budget-chars", type=int, default=4000)
    parser.add_argument("--format", choices=["json", "md"], default="json")
    parser.add_argument(
        "--propose-categories",
        metavar="QUESTION",
        help="Fill this choice question's categories from a text-model sample",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Plan only: counts, requests, no inference"
    )
    args = parser.parse_args(argv)
    started = time.perf_counter()
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    keep = list(dict.fromkeys(args.keep + spec.get("keep", [])))
    task = args.task or spec.get("task")
    if not task:
        raise ValueError("a task is required (spec.task or --task)")
    records, meta = read_inputs(
        args.input,
        spec.get("text_field", args.text_field),
        spec.get("id_field", args.id_field),
        keep,
        args.max_records,
        args.max_chars,
    )
    proposal = None
    if args.propose_categories:
        from .act.text import from_environment

        helper = from_environment()
        if helper is None:
            raise ValueError(
                "--propose-categories needs JEV_TEXT_BASE_URL, JEV_TEXT_API_KEY, JEV_TEXT_MODEL"
            )
        q = spec["questions"].get(args.propose_categories)
        if not q or q.get("type") != "choice":
            raise ValueError("--propose-categories must name a choice question")
        q["criteria"], proposal = propose_categories(records, q, task, helper)
    spec = validate_spec(spec, keep)
    model = spec.get("model", "jev-1.13.0")
    screened_out = []
    usage = {"input_tokens": 0, "output_tokens": 0}
    usage_complete = True
    requests = 0
    if args.dry_run:
        from .cli import chunks, normalize

        parts = list(chunks(normalize(records)))
        planned = analysis.plan(
            parts, task, {"mode": "analyze", "questions": spec["questions"], "model": model}
        )
        print(
            json.dumps(
                {
                    "ok": True,
                    "dry_run": True,
                    "records": len(records),
                    "requests": len(planned["items"]),
                    "deferred": len(planned["deferred"]),
                    "input": meta,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    target = records
    if spec.get("screen"):
        screen_q = {"screen": {"type": "noul", "instructions": spec["screen"]["instructions"]}}
        answers, stats = evaluate(records, task, screen_q, spec.get("context"), args.workers, model)
        usage = {k: usage[k] + stats["usage"][k] for k in usage}
        usage_complete &= stats.get("usage_complete", False)
        requests += stats.get("requests", 0)
        threshold = spec["screen"].get("threshold", 0.5)
        passed = {
            rid
            for rid, e in answers.items()
            if e.get("status") == "OK" and e["answers"]["screen"]["noul"] >= threshold
        }
        screened_out = [r["id"] for r in records if r["id"] not in passed]
        target = [r for r in records if r["id"] in passed]
    answers, stats = (
        evaluate(
            target,
            task,
            spec["questions"],
            spec.get("context"),
            args.workers,
            model,
            spec.get("batch_size", "auto"),
        )
        if target
        else ({}, {"usage": usage | {}, "requests": 0, "usage_complete": True})
    )
    if target:
        usage = {k: usage[k] + stats["usage"][k] for k in usage}
        usage_complete &= stats.get("usage_complete", False)
        requests += stats.get("requests", 0)
    report = aggregate(target, answers, spec, args.budget_chars)
    report.update(
        task=task,
        input=meta,
        screened_out=len(screened_out),
        records=len(records),
        usage=usage,
        usage_complete=usage_complete,
        requests=requests,
        elapsed_ms=round((time.perf_counter() - started) * 1000),
        category_proposal=proposal,
    )
    rate = spec.get("usd_per_million_input", 0.042)
    report["estimated_input_usd"] = round(usage["input_tokens"] * rate / 1e6, 6)
    report["complete"] = report["failed"] == 0 and not meta["truncated"]
    report["ok"] = report["failed"] < max(1, len(target))
    report["archive"] = save_archive(
        {
            "tool": "survey",
            "spec": spec,
            "input": meta,
            "screened_out": screened_out,
            "answers": {rid: e.get("answers", {}) for rid, e in answers.items()},
            "report": report,
        }
    )
    rendered = (
        render_markdown(report)
        if args.format == "md"
        else json.dumps(report, ensure_ascii=False, indent=2)
    )
    record("survey", None, rendered + "\n", report, comparable=False)
    print(rendered)
    return 0 if report["ok"] and report["complete"] else 2
