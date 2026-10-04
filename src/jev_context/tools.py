"""Program-owned collectors and Jev decisions; source evidence stays internal."""

import argparse
import ast
import hashlib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from . import analysis
from .command import collect_command
from .pool import worker_count

HERE = Path(__file__).resolve().parent


def _collect_exact_code(root, pattern, limit=200):
    if limit < 1:
        raise ValueError("limit must be positive")
    root = Path(root).resolve(strict=True)
    hits, meta = collect_command(
        ["rg", "--json", "-e", pattern, "--", str(root)],
        max_bytes=2_000_000,
        split="whole",
        accept_exit=(0, 1),
    )
    if not meta["ok"]:
        raise ValueError("Code search failed or exceeded collection capacity")
    grouped = {}
    capped = False
    n = 0
    for raw in hits[0]["text"].splitlines():
        event = json.loads(raw)
        if event["type"] != "match":
            continue
        data = event["data"]
        if "text" not in data["path"] or "text" not in data["lines"]:
            raise ValueError("Code source must be UTF-8")
        if n >= limit:
            capped = True
            break
        n += 1
        grouped.setdefault(data["path"]["text"], []).append(
            (data["line_number"], data["lines"]["text"])
        )
    texts = {}
    units = {}
    js = []
    errors = {}
    for path in grouped:
        with open(path, "rb") as f:
            raw = f.read(1_000_001)
        if len(raw) > 1_000_000:
            errors[path] = "file_too_large"
            texts[path] = ""
            continue
        try:
            texts[path] = raw.decode("utf-8")
        except UnicodeDecodeError:
            errors[path] = "invalid_utf8"
            texts[path] = ""
            continue
        if Path(path).suffix == ".py":
            try:
                tree = ast.parse(texts[path])
                spans = []

                def walk(node, parents=()):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        spans.append(
                            {
                                "symbol": ".".join((*parents, node.name)),
                                "line": min(
                                    [node.lineno] + [d.lineno for d in node.decorator_list]
                                ),
                                "end_line": node.end_lineno,
                            }
                        )
                    new = (
                        (*parents, node.name)
                        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                        else parents
                    )
                    for child in ast.iter_child_nodes(node):
                        walk(child, new)

                walk(tree)
                units[path] = spans
            except SyntaxError:
                errors[path] = "parse_error"
        elif Path(path).suffix in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go"):
            js.append({"path": path, "text": texts[path]})
        else:
            errors[path] = "unsupported_language"
    if js:
        from .symbols import parse_symbols

        for item in js:
            try:
                units[item["path"]] = parse_symbols(item["path"], item["text"])
            except ImportError:
                errors[item["path"]] = "parser_unavailable"
            except ValueError:
                errors[item["path"]] = "parse_error"
    records = []
    seen = set()
    for path, matches in grouped.items():
        lines = texts[path].splitlines(keepends=True)
        digest = hashlib.sha256(texts[path].encode()).hexdigest()
        for lineno, matched_text in matches:
            stale = lineno > len(lines) or lines[lineno - 1] != matched_text
            spans = [s for s in units.get(path, []) if s["line"] <= lineno <= s["end_line"]]
            span = (
                min(spans, key=lambda s: s["end_line"] - s["line"])
                if spans
                else {
                    "symbol": "<module-window>",
                    "line": max(1, lineno - 8),
                    "end_line": min(len(lines), lineno + 8),
                }
            )
            key = (path, span["line"], span["end_line"])
            if key in seen:
                continue
            seen.add(key)
            relative = str(Path(path).relative_to(root if root.is_dir() else root.parent))
            record = {
                "id": f"{relative}:{span['symbol']}:{span['line']}",
                "text": "".join(lines[span["line"] - 1 : span["end_line"]]),
                "path": path,
                **span,
                "boundary": "symbol" if spans else "window",
                "source_sha256": digest,
            }
            if path in errors or stale:
                record["fetch_error"] = "changed_since_search" if stale else errors[path]
            records.append(record)

    def contains(parent, child):
        return (
            parent is not child
            and parent["path"] == child["path"]
            and parent["boundary"] == "symbol"
            and parent["line"] <= child["line"]
            and parent["end_line"] >= child["end_line"]
        )

    retained = [r for r in records if not any(contains(other, r) for other in records)]
    for record in records:
        if record in retained:
            continue
        owner = next((r for r in retained if contains(r, record)), None)
        if owner is not None:
            owner.setdefault("nested_symbols", []).append(
                {k: record[k] for k in ("symbol", "line", "end_line")}
            )
    return retained, {
        "ok": True,
        "candidate_limit_reached": capped,
        "scope": "lexical rg candidates; Python/JS/TS/Go symbol expansion; not exhaustive semantic indexing",
        "root": str(root),
    }


def collect_code(root, pattern, limit=200, *, query=None, expand_callers=False, max_files=2000):
    records, meta = _collect_exact_code(root, pattern, limit)
    if query is None and not expand_callers:
        return records, meta
    from .retrieval import recall

    records, retrieval = recall(root, records, query, expand_callers, limit, max_files)
    return records, {
        **meta,
        "retrieval": retrieval,
        "candidate_limit_reached": meta["candidate_limit_reached"]
        or retrieval["candidate_limit_reached"],
        "truncated": retrieval["truncated"],
        "scope": "exact rg hits plus bounded lexical/symbol recall and optional Python caller clues; not exhaustive semantic indexing",
    }


SECRET_KEY = re.compile(
    r"(?i)(authorization|cookie|api[-_]?key|access[-_]?token|refresh[-_]?token|password|secret)"
)
SECRET_TEXT = re.compile(
    r"""(?i)(bearer\s+)[^\s,;"']+|\bsk-[A-Za-z0-9_-]{8,}|((?:password|api[-_]?key|(?:access|refresh)[-_]?token|token)["']?\s*[:=]\s*["']?)[^\s,;"']+"""
)
SECRET_HEADER = re.compile(r"(?im)\b(?:authorization|cookie|set-cookie)\s*:\s*[^\r\n]+")


def redact(value):
    if isinstance(value, dict):
        return {k: "[REDACTED]" if SECRET_KEY.search(k) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return SECRET_TEXT.sub("[REDACTED]", SECRET_HEADER.sub("[REDACTED]", value))
    return value


def collect_logs(text, group_by="request_id"):
    try:
        decoded = json.loads(text)
        events = decoded if isinstance(decoded, list) else [decoded]
    except json.JSONDecodeError:
        events = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                events.append({"_parse_error": True, "raw_line": line})
    groups = {}
    parse_errors = 0
    redacted_events = 0
    for lineno, event in enumerate(events, 1):
        if not isinstance(event, dict):
            event = {"_parse_error": True, "raw_line": json.dumps(event)}
        parse_errors += bool(event.get("_parse_error"))
        key = (
            str(event[group_by])
            if group_by in event and isinstance(event[group_by], (str, int))
            else f"ungrouped-line-{lineno}"
        )
        # Keep explicit correlation IDs separate from generated IDs.
        key = ("correlated:" if group_by in event else "uncorrelated:") + key
        safe = redact(event)
        redacted_events += safe != event
        serialized = json.dumps(safe, sort_keys=True, ensure_ascii=False)
        group = groups.setdefault(key, {"events": [], "index": {}, "parse_error": False})
        group["parse_error"] |= bool(event.get("_parse_error"))
        # Coalesce only consecutive exact duplicates, retaining multiplicity and source positions.
        if group["events"] and group["events"][-1]["key"] == serialized:
            entry = group["events"][-1]
            entry["occurrences"] += 1
            entry["lines"].append(lineno)
        else:
            group["events"].append(
                {"key": serialized, "event": safe, "occurrences": 1, "lines": [lineno]}
            )
    records = []
    for key, group in groups.items():
        data = {"events": [{k: v for k, v in e.items() if k != "key"} for e in group["events"]]}
        r = {
            "id": key,
            "text": json.dumps(data, ensure_ascii=False, separators=(",", ":")),
            "event_count": sum(e["occurrences"] for e in group["events"]),
        }
        if group["parse_error"]:
            r["fetch_error"] = "parse_error"
        records.append(r)
    return records, {
        "ok": True,
        "event_count": len(events),
        "groups": len(records),
        "parse_errors": parse_errors,
        "truncated": parse_errors > 0,
        "redacted": redacted_events > 0,
        "redacted_events": redacted_events,
        "order": "observed order within each correlation ID",
    }


def analyze_records(records, task, spec, collection, workers="auto", budget=4000):
    from .cli import chunks, normalize, save_archive

    start = time.perf_counter()
    spec = analysis.validate(spec)
    worker_count(1, workers)
    records = normalize(records)
    parts = list(chunks(records))
    for part, record in zip(parts, records):
        part["source"] = {k: v for k, v in record.items() if k not in ("id", "text", "sha256")}
    archive = save_archive({"records": records, "collection": collection})
    incomplete = bool(
        collection.get("truncated")
        or collection.get("candidate_limit_reached")
        or collection.get("scope_missing")
        or collection.get("scope_ambiguous")
    )
    candidates = [p for p in parts if not p["source"].get("fetch_error")]
    if spec.get("mode") == "choose" and len(candidates) != len(parts):
        incomplete = True
    if collection.get("ok", True) and not (spec.get("mode") == "choose" and incomplete):
        js, stats = analysis.evaluate(candidates, task, workers=workers, spec=spec)
    else:
        js, stats = (
            {},
            {
                "ok": False,
                "usage": {"input_tokens": 0, "output_tokens": 0},
                "usage_complete": True,
                "requests": 0,
            },
        )
    summary = analysis.summarize(parts, js, spec)
    if incomplete:
        summary["complete"] = False
    excerpts = analysis.select(parts, js, spec, budget)
    receipt = save_archive(
        {
            "records": records,
            "collection": collection,
            "task": task,
            "analysis": spec,
            "judgments": js,
            "telemetry": stats,
            "summary": summary,
        }
    )
    return {
        **summary,
        "ok": bool(stats["ok"]) and collection.get("ok", True),
        "archive": archive,
        "receipt": receipt,
        "excerpts": excerpts,
        "scope_incomplete": incomplete,
        "cache_enabled": False,
        "telemetry": {
            k: v
            for k, v in stats.items()
            if k
            in (
                "usage",
                "usage_complete",
                "unknown_usage_attempts",
                "requests",
                "workers",
                "network_questions",
                "missing_context",
                "missing_record_fields",
            )
        },
        "analysis_ms": round((time.perf_counter() - start) * 1000),
    }


def guard_code_sources(result, records):
    """Revalidate all admitted source revisions after inference, including exclusions."""
    revisions, changed = {}, []
    for record in records:
        path = record.get("path")
        if not path or not record.get("source_sha256"):
            continue
        if path not in revisions:
            try:
                with open(path, "rb") as stream:
                    raw = stream.read(1_000_001)
                revisions[path] = hashlib.sha256(raw).hexdigest() if len(raw) <= 1_000_000 else None
            except OSError:
                revisions[path] = None
        if revisions[path] != record["source_sha256"]:
            changed.append(record["id"])
    if changed:
        result["selected_ids"] = [rid for rid in result["selected_ids"] if rid not in changed]
        result["review_ids"] = list(dict.fromkeys(result["review_ids"] + changed))
        result["complete"] = False
        result["changed_sources"] = changed
        for row in result["excerpts"]:
            if row.get("source_id") in changed:
                row.update(decision="REVIEW", status="SOURCE_CHANGED")
    return result


def safe_control(record):
    result = {k: redact(v) for k, v in record.items() if k != "value"}
    if record.get("href"):
        url = urllib.parse.urlsplit(record["href"])
        host = url.hostname or ""
        if url.port:
            host += ":" + str(url.port)
        result["href"] = urllib.parse.urlunsplit((url.scheme, host, url.path, "", ""))
    return result


def browser_call(session, tab, policy, op="observe", **kwargs):
    if not re.fullmatch(r"[A-Za-z0-9._-]+", session):
        raise ValueError("Invalid named browser session")
    expression = (
        "("
        + (HERE / "locator_dom.js").read_text(encoding="utf-8")
        + ")("
        + json.dumps({"policy": policy, "op": op, **kwargs})
        + ")"
    )
    request = urllib.request.Request(
        "http://127.0.0.1:9377/tabs/" + urllib.parse.quote(tab, safe="") + "/evaluate",
        data=json.dumps({"userId": "camofox-" + session, "expression": expression}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=40) as response:
        return json.load(response)["result"]


def apply_guard(result, guard):
    result = {**result, "executed": False, "target_guard": guard}
    if not guard.get("ok"):
        result["review_ids"] = list(dict.fromkeys(result["review_ids"] + result["selected_ids"]))
        result["selected_ids"] = []
        result["complete"] = False
        for row in result["excerpts"]:
            if row.get("decision") == "MATCH":
                row["decision"] = "REVIEW"
    return result


def ambiguous_controls(records, selected_id):
    selected = next((r for r in records if r["id"] == selected_id), None)
    if selected is None:
        return []
    fields = ("text", "role", "section", "href", "enabled")
    same = [r["id"] for r in records if all(r.get(k) == selected.get(k) for k in fields)]
    return same if len(same) > 1 else []


def _utf8_stdio():
    """Windows consoles default to the locale codepage (e.g. GBK); records and output are UTF-8."""
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def main(argv=None):
    _utf8_stdio()
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("code-search", "diff-review", "locate", "triage"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--task", required=True)
        cmd.add_argument(
            "--analysis",
            help="Decision spec with sourced context, required fields and typed questions",
        )
        cmd.add_argument("--workers", default="auto")
        cmd.add_argument("--budget-chars", type=int, default=4000)
        if name == "code-search":
            cmd.add_argument("pattern")
            cmd.add_argument("--root", default=".")
            cmd.add_argument("--limit", type=int, default=200)
            cmd.add_argument(
                "--query", help="Optional lexical recall query; regex hits retain priority"
            )
            cmd.add_argument(
                "--expand-callers",
                action="store_true",
                help="Add one-hop Python syntactic caller clues, not resolved calls",
            )
            cmd.add_argument("--max-files", type=int, default=2000)
        elif name == "diff-review":
            cmd.add_argument("--root", default=".")
            revisions = cmd.add_mutually_exclusive_group(required=True)
            revisions.add_argument("--base", help="Before commit/ref, pinned before collection")
            revisions.add_argument("--staged", action="store_true")
            revisions.add_argument("--unstaged", action="store_true")
            cmd.add_argument("--head", help="After commit/ref; defaults to HEAD with --base")
            cmd.add_argument("--limit", type=int, default=200)
            cmd.add_argument("--max-file-bytes", type=int, default=64_000)
            cmd.add_argument("--max-total-bytes", type=int, default=2_000_000)
        elif name == "locate":
            cmd.add_argument("--session", required=True)
            cmd.add_argument("--tab", required=True)
            cmd.add_argument("--origin", required=True)
            cmd.add_argument("--scope", default="body")
            cmd.add_argument("--limit", type=int, default=200)
        else:
            cmd.add_argument("--input")
            cmd.add_argument("--collect", nargs=argparse.REMAINDER)
            cmd.add_argument("--group-by", default="request_id")
    args = p.parse_args(argv)
    worker_count(1, args.workers)
    if args.budget_chars < 1 or not args.task.strip():
        raise ValueError("Task and positive evidence budget required")
    spec = (
        json.loads(Path(args.analysis).read_text(encoding="utf-8"))
        if args.analysis
        else {"mode": "choose"}
        if args.command == "locate"
        else None
    )
    spec = analysis.validate(spec)
    if args.command == "triage" and "fields" not in spec and "output" not in spec:
        spec["fields"] = ["source_id", "answers", "source"]
    if args.command == "locate" and spec.get("mode") != "choose":
        raise ValueError("locate requires choose mode")
    admission = analysis.context_admission(spec)
    if admission:
        print(analysis.render(admission, spec))
        return 2
    start = time.perf_counter()
    if args.command == "code-search":
        records, collection = collect_code(
            args.root,
            args.pattern,
            args.limit,
            query=args.query,
            expand_callers=args.expand_callers,
            max_files=args.max_files,
        )
    elif args.command == "diff-review":
        from .diff import collect_diff

        records, collection = collect_diff(
            args.root,
            base=args.base,
            head=args.head,
            staged=args.staged,
            unstaged=args.unstaged,
            limit=args.limit,
            max_file_bytes=args.max_file_bytes,
            max_total_bytes=args.max_total_bytes,
        )
    elif args.command == "locate":
        if not 1 <= args.limit <= 253:
            raise ValueError("locate limit must be 1..253")
        policy = {"origin": args.origin, "scope": args.scope, "limit": args.limit}
        observed = browser_call(args.session, args.tab, policy)
        records = [safe_control(r) for r in observed["records"] if r["enabled"]]
        collection = {k: v for k, v in observed.items() if k != "records"}
        collection["excluded_disabled"] = len(observed["records"]) - len(records)
    else:
        if bool(args.input) == bool(args.collect):
            raise ValueError("Choose --input or --collect")
        if args.collect:
            command = args.collect[1:] if args.collect[:1] == ["--"] else args.collect
            data, collection = collect_command(command, split="whole")
            text = data[0]["text"]
        else:
            if args.input == "-":
                stream = getattr(sys.stdin, "buffer", None)
                raw = (
                    stream.read(2_000_001) if stream else sys.stdin.read(2_000_001).encode("utf-8")
                )
            else:
                with open(args.input, "rb") as stream:
                    raw = stream.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ValueError("Log input exceeds 2 MB; narrow collection")
            text = raw.decode("utf-8")
            collection = {"ok": True}
        from .cli import save_archive

        raw_archive = save_archive(
            {"records": [{"id": "raw", "text": text}], "collection": collection}
        )
        records, log_meta = collect_logs(text, args.group_by)
        collection = {
            **log_meta,
            **collection,
            "truncated": bool(log_meta.get("truncated") or collection.get("truncated")),
            "raw_archive": raw_archive,
        }
    result = analyze_records(records, args.task, spec, collection, args.workers, args.budget_chars)
    issues = [
        key
        for key in ("scope_missing", "scope_ambiguous", "candidate_limit_reached", "parse_errors")
        if collection.get(key)
    ]
    if issues:
        result["collection_issues"] = issues
    if args.command == "locate":
        if result["selected_ids"]:
            duplicates = ambiguous_controls(records, result["selected_ids"][0])
            if duplicates:
                guard = {
                    "ok": False,
                    "reason": "indistinguishable_controls",
                    "candidate_ids": duplicates,
                }
                result["review_ids"] = list(dict.fromkeys(result["review_ids"] + duplicates))
            else:
                guard = browser_call(
                    args.session,
                    args.tab,
                    policy,
                    "guard",
                    token=observed["token"],
                    id=result["selected_ids"][0],
                )
            result = apply_guard(result, guard)
        else:
            result["executed"] = False
    elif args.command in ("code-search", "diff-review"):
        changed = []
        if args.command == "diff-review":
            from .diff import changed_diff_sources

            changed = changed_diff_sources(records, collection)
        else:
            result = guard_code_sources(result, records)
        if changed:
            result["selected_ids"] = [rid for rid in result["selected_ids"] if rid not in changed]
            result["review_ids"] = list(dict.fromkeys(result["review_ids"] + changed))
            result["complete"] = False
            result["changed_sources"] = changed
            for row in result["excerpts"]:
                if row.get("source_id") in changed:
                    row.update(decision="REVIEW", status="SOURCE_CHANGED")
    result.update(tool=args.command, elapsed_ms=round((time.perf_counter() - start) * 1000))
    from .cli import save_archive

    result["analysis_receipt"] = result["receipt"]
    result["receipt"] = save_archive({"records": records, "result": result})
    rendered = analysis.render(result, spec)
    from .stats import record

    record(
        args.command,
        json.dumps(records, ensure_ascii=False, separators=(",", ":")),
        rendered + "\n",
        result,
    )
    print(rendered)
    return 0 if result["ok"] and result["complete"] else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({"ok": False, "error_type": type(error).__name__}), file=sys.stderr)
        raise SystemExit(1)
