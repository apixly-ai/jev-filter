#!/usr/bin/env python3
"""Task-aware evidence selection. No inference cache and no generated summaries."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import analysis
from .command import collect_command


def collect_search(root, pattern, limit):
    """Retain rg matches and adjacent lines, with an explicit bounded scope."""
    root = Path(root).resolve(strict=True)
    records, capped = [], False
    # No shell execution. rg respects ignore rules and skips hidden files by default.
    with tempfile.TemporaryFile() as errors:
        proc = subprocess.Popen(
            [
                "rg",
                "--json",
                "--no-heading",
                "--context",
                "2",
                "--max-columns",
                "4000",
                "-e",
                pattern,
                "--",
                str(root),
            ],
            stdout=subprocess.PIPE,
            stderr=errors,
            text=True,
        )
        try:
            for raw in proc.stdout:
                event = json.loads(raw)
                if event["type"] not in ("match", "context"):
                    continue
                data = event["data"]
                if "text" not in data["path"] or "text" not in data["lines"]:
                    raise ValueError("Non-UTF8 search output cannot be represented")
                if len(records) >= limit:
                    capped = True
                    proc.terminate()
                    break
                records.append(
                    {
                        "id": f"s{len(records) + 1}",
                        "path": data["path"]["text"],
                        "line": data["line_number"],
                        "text": data["lines"]["text"],
                    }
                )
        finally:
            proc.stdout.close()
            proc.wait()
        if not capped and proc.returncode not in (0, 1):
            raise ValueError("rg failed; check pattern and readable search scope")
    grouped = []
    for record in records:
        previous = grouped[-1] if grouped else None
        if (
            previous
            and previous["path"] == record["path"]
            and previous["end_line"] + 1 == record["line"]
        ):
            previous["text"] += record["text"]
            previous["end_line"] = record["line"]
        else:
            grouped.append({**record, "end_line": record["line"]})
    return grouped, {
        "root": str(root),
        "pattern": pattern,
        "candidate_limit_reached": capped,
        "scope": "rg matches and 2 adjacent lines; ignore rules apply; not exhaustive semantic search",
    }


def normalize(records):
    if isinstance(records, dict):
        records = records["records"]
    if not isinstance(records, list):
        raise ValueError("Input must be an array or {records:[...]}")
    seen, result = set(), []
    for i, value in enumerate(records):
        if not isinstance(value, dict) or not isinstance(value.get("text"), str):
            raise ValueError("Each record requires text")
        record = dict(value)
        record.setdefault("id", f"s{i + 1}")
        if not isinstance(record["id"], str) or not record["id"] or record["id"] in seen:
            raise ValueError("Record IDs must be unique nonempty strings")
        seen.add(record["id"])
        record["sha256"] = hashlib.sha256(record["text"].encode()).hexdigest()
        result.append(record)
    return result


def chunks(records, max_chars=None):
    """Keep caller-defined semantic records intact; oversized records require segmentation."""
    for record in records:
        yield {
            "id": f"p{record['id']}:0",
            "source_id": record["id"],
            "start": 0,
            "end": len(record["text"]),
            "text": record["text"],
        }


def save_archive(payload, destination=None):
    if destination:
        path = Path(destination).expanduser().absolute()
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    else:
        fd, name = tempfile.mkstemp(prefix="jev-context-", suffix=".json")
        path = Path(name)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False)
    return str(path)


def _act_main():
    from .act.cli import main as act_main

    return act_main


def _survey_main():
    from .survey import main as survey_main

    return lambda argv: survey_main(argv[1:])


HOSTED = {"browse": _act_main, "extract": _act_main, "desktop": _act_main, "survey": _survey_main}
HOSTED_HELP = {
    "browse": "Hosted browser execution toward a goal",
    "extract": "Structure a web page into records and select relevant ones",
    "desktop": "Hosted desktop execution in one Windows/macOS application",
    "survey": "Typed judgments over many records, aggregated into an evidence report",
}


def _utf8_stdio():
    """Windows consoles default to the locale codepage (e.g. GBK); records and output are UTF-8."""
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def main():
    _utf8_stdio()
    if len(sys.argv) > 1 and sys.argv[1] == "stats":
        from .stats import main as stats_main

        return stats_main(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] in ("code-search", "locate", "triage"):
        from .tools import main as semantic_main

        return semantic_main(sys.argv[1:])
    if len(sys.argv) > 1 and sys.argv[1] in HOSTED:
        return HOSTED[sys.argv[1]]()(sys.argv[1:])
    from . import __version__

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version="jev-filter " + __version__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("search", "query", "exec"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--task", required=True, help="Question/goal and constraints; sent to Jev")
        cmd.add_argument(
            "--budget-chars",
            type=int,
            default=6000,
            help="Excerpt character budget, not tokens or JSON size",
        )
        cmd.add_argument(
            "--workers", default="auto", help="auto or 1..30; independent requests only"
        )
        cmd.add_argument(
            "--mode", choices=["auto", "filter", "choose", "analyze", "passthrough"], default="auto"
        )
        cmd.add_argument(
            "--batch-size",
            default="auto",
            help="auto or positive integer; independent requests use --workers",
        )
        cmd.add_argument(
            "--diagnostics",
            action="store_true",
            help="Include detailed telemetry and command metadata",
        )
        cmd.add_argument(
            "--plan",
            action="store_true",
            help="Collect once and show inference plan without calling Jev",
        )
        cmd.add_argument(
            "--analysis",
            help="Decision spec: context/required_context, questions/requirements, filters and output",
        )
        cmd.add_argument(
            "--format", choices=["json", "jsonl", "text"], help="Override rendering format"
        )
        cmd.add_argument(
            "--archive", help="New local evidence file; never overwritten or reused for inference"
        )
        cmd.add_argument(
            "--max-parts",
            type=int,
            default=2048,
            help="Maximum passages sent; remainder retained for review",
        )
        if name == "search":
            cmd.add_argument("pattern", help="rg regex used to collect candidates")
            cmd.add_argument("--root", default=".")
            cmd.add_argument("--limit", type=int, default=200)
        elif name == "exec":
            cmd.add_argument("--cwd")
            cmd.add_argument("--timeout", type=float, default=30)
            cmd.add_argument("--max-bytes", type=int, default=2000000)
            cmd.add_argument(
                "--split", choices=["auto", "lines", "paragraphs", "whole", "json"], default="auto"
            )
            cmd.add_argument("--accept-exit", type=int, nargs="+", default=[0])
            cmd.add_argument(
                "argv", nargs=argparse.REMAINDER, help="Literal command argv following --"
            )
        else:
            cmd.add_argument("--input", required=True, help="JSON path or - for stdin")
    for name in ("code-search", "locate", "triage"):
        commands.add_parser(
            name,
            add_help=False,
            help="Specialized collection and semantic analysis; see " + name + " --help",
        )
    for name, text in HOSTED_HELP.items():
        commands.add_parser(name, add_help=False, help=text + "; see " + name + " --help")
    commands.add_parser("stats", help="Local usage ledger and savings dashboard")
    doctor = commands.add_parser(
        "doctor", help="Check local setup; --live makes one billable synthetic request"
    )
    doctor.add_argument("--live", action="store_true")
    batch = commands.add_parser(
        "batch", help="Internal typed workflow requests; never returns source states"
    )
    batch.add_argument("--input", required=True)
    batch.add_argument("--workers", default="auto")
    listing = commands.add_parser("list", help="List every retained source without a model call")
    listing.add_argument("archive")
    read = commands.add_parser("read", help="Read retained supplied text without a model call")
    read.add_argument("archive")
    read.add_argument("--id", required=True)
    args = parser.parse_args()
    if args.command == "doctor":
        from .doctor import check

        result = check(args.live)
        print(json.dumps(result))
        return 0 if result["ok"] else 1
    if args.command == "batch":
        from .batch import run

        with sys.stdin if args.input == "-" else open(args.input, encoding="utf-8") as stream:
            items = json.load(stream)
        result = run(items, workers=args.workers)
        rendered = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        from .stats import record

        record("batch", None, rendered + "\n", result, comparable=False)
        print(rendered)
        return 0 if result["ok"] else 2
    if args.command == "list":
        payload = json.loads(Path(args.archive).read_text(encoding="utf-8"))
        print(
            json.dumps(
                [
                    {k: v for k, v in r.items() if k != "text"} | {"chars": len(r["text"])}
                    for r in payload["records"]
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.command == "read":
        payload = json.loads(Path(args.archive).read_text(encoding="utf-8"))
        record = next((r for r in payload["records"] if r["id"] == args.id), None)
        if record is None:
            raise ValueError("Unknown source ID")
        print(json.dumps(record, ensure_ascii=False))
        return 0
    if not args.task.strip() or len(args.task) > 12000:
        raise ValueError("task must contain 1..12000 characters")
    if not 1 <= args.budget_chars or not 1 <= args.max_parts <= 10000:
        raise ValueError("Positive budget and max-parts in 1..10000 required")
    started = time.perf_counter()
    spec = analysis.validate(
        json.loads(Path(args.analysis).read_text(encoding="utf-8")) if args.analysis else None
    )
    if args.mode != "auto":
        spec["mode"] = args.mode
    if args.batch_size != "auto":
        spec["batch_size"] = int(args.batch_size)
    spec = analysis.validate(spec)
    from .pool import worker_count

    worker_count(1, args.workers)  # validate before executing a caller command
    if args.format:
        spec["format"] = args.format
    admission = analysis.context_admission(spec)
    if admission:
        print(analysis.render(admission, spec))
        return 2
    if args.command == "search":
        if args.limit < 1:
            raise ValueError("limit must be positive")
        records, collection = collect_search(args.root, args.pattern, args.limit)
    elif args.command == "exec":
        argv = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
        records, collection = collect_command(
            argv, args.cwd, args.timeout, args.max_bytes, args.split, args.accept_exit
        )
    else:
        with sys.stdin if args.input == "-" else open(args.input, encoding="utf-8") as stream:
            records = json.load(stream)
        collection = {"scope": "supplied records only; no URLs fetched"}
    records = normalize(records)
    parts = list(chunks(records))
    if (
        args.mode == "auto"
        and not args.analysis
        and collection.get("ok", True)
        and sum(len(r["text"]) for r in records) <= 1200
    ):
        spec["mode"] = "passthrough"
    mode = spec.get("mode", "filter")
    # Save originals before network activity; an archive is a receipt, never an inference cache.
    archive = save_archive({"records": records, "collection": collection}, args.archive)
    by_id = {r["id"]: r for r in records}
    for part in parts:
        source = by_id[part["source_id"]]
        part["source"] = {k: v for k, v in source.items() if k not in ("id", "text")}
    if args.plan:
        planned = analysis.plan(parts, args.task, spec)
        print(
            json.dumps(
                {
                    "mode": mode,
                    "requests": len(planned["items"]),
                    "workers": worker_count(len(planned["items"]), args.workers),
                    "questions": sum(len(i["request"]["questions"]) for i in planned["items"]),
                    "deferred": planned["deferred"],
                    "archive": archive,
                },
                ensure_ascii=False,
            )
        )
        return 0
    scope_incomplete = bool(
        collection.get("truncated") or collection.get("candidate_limit_reached")
    )
    if collection.get("ok", True) and not (mode == "choose" and scope_incomplete):
        candidates = parts if mode == "choose" else parts[: args.max_parts]
        judgments, telemetry = analysis.evaluate(candidates, args.task, args.workers, spec)
    else:
        judgments, telemetry = (
            {},
            {
                "ok": False,
                "usage": {"input_tokens": 0, "output_tokens": 0},
                "usage_complete": True,
                "network_questions": 0,
                "cache_hit_questions": 0,
            },
        )
    summary = analysis.summarize(parts, judgments, spec)
    if mode == "passthrough":
        judgments = {
            p["id"]: {"status": "PASSTHROUGH", "answers": {}, "decision": "REVIEW"} for p in parts
        }
        summary = {
            "selected_ids": [],
            "review_ids": [p["source_id"] for p in parts],
            "complete": False,
            "excluded_count": 0,
        }
    if scope_incomplete or not collection.get("ok", True):
        summary["complete"] = False
    selected = analysis.select(parts, judgments, spec, args.budget_chars)
    full_receipt = save_archive(
        {
            "records": records,
            "collection": collection,
            "analysis": spec,
            "task": args.task,
            "judgments": judgments,
            "summary": summary,
            "telemetry": telemetry,
        }
    )
    output = {
        **summary,
        "mode": mode,
        "receipt": full_receipt,
        "scope_incomplete": scope_incomplete,
        "ok": telemetry["ok"] and collection.get("ok", True),
        "archive": archive,
        "cache_enabled": False,
        "collection": collection,
        "source_count": len(records),
        "part_count": len(parts),
        "not_evaluated_parts": len(parts) - len(judgments),
        "input_chars": sum(len(r["text"]) for r in records),
        "shown_chars": sum(len(p["text"]) for p in selected),
        "excerpts": selected,
        "telemetry": telemetry,
        "elapsed_ms": round((time.perf_counter() - started) * 1000),
        "notice": "Selection is fallible; omitted text is not evidence of absence. Read archive by source ID. "
        "Archive retains supplied text only. Command failure is not retried or analyzed.",
    }
    if not args.diagnostics:
        output["collection"] = {
            k: v
            for k, v in collection.items()
            if k
            in (
                "ok",
                "exit_code",
                "stop_reason",
                "truncated",
                "candidate_limit_reached",
                "parse_error",
            )
        }
        output["telemetry"] = {
            k: v
            for k, v in telemetry.items()
            if k
            in (
                "usage",
                "usage_complete",
                "requests",
                "workers",
                "network_questions",
                "missing_context",
                "missing_record_fields",
            )
        }
        output.pop("notice", None)
        output.pop("not_evaluated_parts", None)
        output.pop("input_chars", None)
        output.pop("shown_chars", None)
        output.pop("part_count", None)
    rendered = analysis.render(output, spec)
    from .stats import record

    record(
        args.command,
        json.dumps(records, ensure_ascii=False, separators=(",", ":")),
        rendered + "\n",
        output,
    )
    print(rendered)
    return 0 if output["ok"] and (output["complete"] or mode == "passthrough") else 2


def entrypoint():
    """Console entrypoint with bounded, non-secret error output."""
    try:
        return main()
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        print(json.dumps({"ok": False, "error_type": type(error).__name__}), file=sys.stderr)
        return 1
