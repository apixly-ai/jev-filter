"""Bounded lexical recall and syntactic call clues; no inference, execution or cache."""

import ast
import hashlib
import math
import re
from collections import Counter
from pathlib import Path

from .command import collect_command

EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go"}
STOPWORDS = frozenset("a an and are as at be by for from in is it of on or the to with".split())


def tokens(text):
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return [t for t in re.findall(r"[^\W_]+", separated.lower()) if t not in STOPWORDS]


def _python_units(text):
    tree = ast.parse(text)
    spans = []

    def walk(node, parents=()):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            calls = set()
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Name):
                        calls.add(child.func.id)
                    elif isinstance(child.func, ast.Attribute):
                        calls.add(child.func.attr)
            spans.append(
                {
                    "symbol": ".".join((*parents, node.name)),
                    "line": min([node.lineno] + [d.lineno for d in node.decorator_list]),
                    "end_line": node.end_lineno,
                    "calls": sorted(calls),
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
    return spans


def _corpus(root, max_files, max_bytes):
    if root.is_file():
        paths, listing_complete = [root], True
    else:
        output, listing = collect_command(
            ["rg", "--files", "-0", "--", str(root)], split="whole", accept_exit=(0, 1)
        )
        paths = sorted(Path(p) for p in output[0]["text"].split("\0") if p)
        listing_complete = listing["ok"]
    paths = [p for p in paths if p.suffix in EXTENSIONS]
    capped = len(paths) > max_files
    records, errors, total = [], [], 0
    for path in paths[:max_files]:
        relative = str(path.relative_to(root if root.is_dir() else root.parent))
        try:
            if path.is_symlink():
                raise OSError("symlink_not_followed")
            with path.open("rb") as stream:
                raw = stream.read(min(1_000_001, max_bytes - total + 1))
            if len(raw) > 1_000_000:
                errors.append({"path": relative, "error": "file_too_large"})
                continue
            if total + len(raw) > max_bytes:
                errors.append({"path": relative, "error": "corpus_byte_limit"})
                break
            total += len(raw)
            text = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            errors.append({"path": relative, "error": "unreadable_or_invalid_utf8"})
            continue
        error = None
        try:
            if path.suffix == ".py":
                spans = _python_units(text)
            else:
                from .symbols import parse_symbols

                spans = parse_symbols(str(path), text)
        except ImportError:
            spans, error = [], "parser_unavailable"
        except (SyntaxError, ValueError):
            spans, error = [], "parse_error"
        if not spans:
            spans = [{"symbol": "<module>", "line": 1, "end_line": len(text.splitlines())}]
        if error:
            errors.append({"path": relative, "error": error})
        lines = text.splitlines(keepends=True)
        for span in spans:
            record = {
                "id": f"{relative}:{span['symbol']}:{span['line']}",
                "text": "".join(lines[span["line"] - 1 : span["end_line"]]),
                "path": str(path),
                **span,
                "boundary": "window" if span["symbol"] == "<module>" else "symbol",
                "source_sha256": hashlib.sha256(raw).hexdigest(),
            }
            if error:
                record["fetch_error"] = error
            records.append(record)
    return records, {
        "files_considered": min(len(paths), max_files),
        "file_limit_reached": capped,
        "corpus_bytes": total,
        "file_errors": errors,
        "listing_complete": listing_complete,
    }


def recall(root, exact, query, expand_callers, limit, max_files=2000, max_bytes=8_000_000):
    if not 1 <= max_files <= 10_000 or not 1 <= max_bytes <= 32_000_000:
        raise ValueError("Recall requires max_files 1..10000 and max_bytes 1..32000000")
    if query is not None and (not query.strip() or len(query) > 2000):
        raise ValueError("Recall query requires 1..2000 nonblank characters")
    root = Path(root).resolve(strict=True)
    corpus, meta = _corpus(root, max_files, max_bytes)
    terms = set(tokens(query or ""))
    documents = []
    for row in corpus:
        counts = Counter(tokens(row["text"]))
        counts.update(tokens(row["symbol"]) * 3)
        counts.update(
            tokens(str(Path(row["path"]).relative_to(root if root.is_dir() else root.parent)))
        )
        documents.append(counts)
    average = sum(sum(d.values()) for d in documents) / max(1, len(documents))
    frequency = {term: sum(term in d for d in documents) for term in terms}
    ranked = []
    for row, document in zip(corpus, documents):
        score = 0.0
        length = sum(document.values())
        for term in terms:
            tf = document[term]
            if tf:
                idf = math.log(
                    1 + (len(documents) - frequency[term] + 0.5) / (frequency[term] + 0.5)
                )
                score += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * length / max(1, average)))
        if score > 0:
            ranked.append((score, row))
    ranked.sort(key=lambda item: (-item[0], item[1]["id"]))
    result = {}
    for row in exact:
        result[row["id"]] = {**row, "retrieval": {"channels": ["exact"]}}
    for score, row in ranked[:limit]:
        if row["id"] in result:
            result[row["id"]]["retrieval"]["channels"].append("lexical")
            result[row["id"]]["retrieval"]["score"] = round(score, 6)
        else:
            result[row["id"]] = {
                **row,
                "retrieval": {"channels": ["lexical"], "score": round(score, 6)},
            }
    if expand_callers:
        names = {row["symbol"].rsplit(".", 1)[-1] for row in result.values()}
        for row in corpus:
            clues = sorted(names.intersection(row.get("calls", [])))
            if clues:
                if row["id"] not in result:
                    result[row["id"]] = {**row, "retrieval": {"channels": []}}
                result[row["id"]]["retrieval"]["channels"].append("caller")
                result[row["id"]]["retrieval"]["call_clues"] = clues
    # A broad parent already contains a nested hit; do not send duplicate evidence.
    rows = list(result.values())
    retained = []
    for row in rows:
        owner = next(
            (
                other
                for other in rows
                if other is not row
                and other["path"] == row["path"]
                and other["line"] <= row["line"]
                and other["end_line"] >= row["end_line"]
                and (other["line"], other["end_line"]) != (row["line"], row["end_line"])
            ),
            None,
        )
        if owner is not None:
            owner.setdefault("nested_symbols", []).append(
                {k: row[k] for k in ("symbol", "line", "end_line")}
            )
            for channel in row["retrieval"]["channels"]:
                if channel not in owner["retrieval"]["channels"]:
                    owner["retrieval"]["channels"].append(channel)
            continue
        retained.append(row)
    capped = len(retained) > limit or len(ranked) > limit
    return retained[:limit], {
        **meta,
        "query": query,
        "ranking": "BM25 over tokenized source, weighted symbol names and paths",
        "call_resolution": "one-hop syntactic name clues, not resolved calls",
        "call_languages": ["Python"],
        "candidate_limit_reached": capped,
        "truncated": bool(
            meta["file_errors"] or meta["file_limit_reached"] or not meta["listing_complete"]
        ),
    }
