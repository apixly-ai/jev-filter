"""Program-owned Git snapshots for caller-specified ranges; no generated commands."""

import hashlib
import json
import re
from pathlib import Path

from .command import collect_command

OID = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")


def _git(root, argv, max_bytes=2_000_000):
    records, meta = collect_command(
        ["git", "--literal-pathspecs", "-C", str(root), *argv],
        split="whole",
        max_bytes=max_bytes,
    )
    return records[0]["text"], meta


def _commit(root, ref):
    if not isinstance(ref, str) or not ref or ref.startswith("-") or "\0" in ref:
        raise ValueError("Git revisions must be explicit non-option references")
    value, meta = _git(root, ["rev-parse", "--verify", "--end-of-options", ref + "^{commit}"], 4096)
    value = value.strip()
    if not meta["ok"] or not OID.fullmatch(value):
        raise ValueError("Git revision must resolve to one existing commit")
    return value


def _snapshot(root, path, oid, mode, max_bytes, worktree=False):
    if not worktree and not oid.strip("0"):
        return None, None, None, 0
    if mode == "160000":
        return None, None, "submodule_not_expanded", 0
    if worktree:
        location = root / path
        try:
            if location.is_symlink():
                return None, None, "symlink_not_followed", 0
            resolved = location.resolve()
            if not resolved.is_relative_to(root):
                return None, None, "path_outside_repository", 0
            if not location.exists():
                return None, None, None, 0
            with location.open("rb") as stream:
                raw = stream.read(max_bytes + 1)
            if len(raw) > max_bytes:
                return None, None, "file_too_large", len(raw)
            text = raw.decode("utf-8")
            if "\0" in text:
                return None, hashlib.sha256(raw).hexdigest(), "binary_or_invalid_utf8", len(raw)
            return text, hashlib.sha256(raw).hexdigest(), None, len(raw)
        except UnicodeDecodeError:
            return None, hashlib.sha256(raw).hexdigest(), "binary_or_invalid_utf8", len(raw)
        except OSError:
            return None, None, "unreadable_worktree", 0
    size, meta = _git(root, ["cat-file", "-s", oid], 4096)
    if not meta["ok"] or not size.strip().isdigit():
        return None, None, "unreadable_blob", 0
    size = int(size.strip())
    if size > max_bytes:
        return None, None, "file_too_large", size
    text, meta = _git(root, ["cat-file", "blob", oid], max(1, max_bytes + 1))
    if not meta["ok"]:
        return None, None, "unreadable_blob", size
    # collect_command decodes with replacement. Reject replacement characters conservatively
    # rather than silently treating non-UTF-8 evidence as trustworthy text.
    if "\0" in text or "\ufffd" in text:
        return None, None, "binary_or_invalid_utf8", size
    return text, hashlib.sha256(text.encode()).hexdigest(), None, size


def collect_diff(
    root,
    *,
    base=None,
    head=None,
    staged=False,
    unstaged=False,
    limit=200,
    max_file_bytes=64_000,
    max_total_bytes=2_000_000,
):
    if sum((base is not None, staged, unstaged)) != 1 or (head is not None and base is None):
        raise ValueError(
            "Choose exactly one --base, --staged or --unstaged; --head requires --base"
        )
    if not 1 <= limit <= 2000 or not 1 <= max_file_bytes <= 1_000_000:
        raise ValueError("Diff requires limit 1..2000 and max_file_bytes 1..1000000")
    if not 1 <= max_total_bytes <= 16_000_000:
        raise ValueError("Diff requires max_total_bytes 1..16000000")
    root = Path(root).resolve(strict=True)
    value, meta = _git(root, ["rev-parse", "--show-toplevel"], 4096)
    if not meta["ok"]:
        raise ValueError("Diff root must be inside a Git working tree")
    root = Path(value.strip()).resolve(strict=True)
    before = None if unstaged else _commit(root, base if base is not None else "HEAD")
    after = _commit(root, head or "HEAD") if base is not None else None
    scope = "commits" if base is not None else "staged" if staged else "unstaged"
    args = ["diff", "--raw", "--abbrev=64", "-z", "--no-renames", "--no-ext-diff", "--no-textconv"]
    if scope == "commits":
        args.extend([before, after])
    elif staged:
        args.extend(["--cached", before])
    args.append("--")
    raw, command = _git(root, args)
    segments = raw.split("\0")
    changes = []
    parse_error = False
    for offset in range(0, len(segments) - 1, 2):
        header, path = segments[offset : offset + 2]
        fields = header.removeprefix(":").split()
        if len(fields) != 5 or not path or "\ufffd" in path:
            parse_error = True
            continue
        old_mode, new_mode, old_oid, new_oid, status = fields
        if not OID.fullmatch(old_oid) or not OID.fullmatch(new_oid):
            parse_error = True
            continue
        changes.append((path, old_mode, new_mode, old_oid, new_oid, status))
    records, errors, total = [], [], 0
    for path, old_mode, new_mode, old_oid, new_oid, status in changes[:limit]:
        error = None
        before_limit = min(max_file_bytes, max(0, max_total_bytes - total))
        before_text, before_hash, before_error, before_bytes = _snapshot(
            root, path, old_oid, old_mode, before_limit
        )
        total += min(before_bytes, before_limit)
        after_limit = min(max_file_bytes, max(0, max_total_bytes - total))
        after_text, after_hash, after_error, after_bytes = _snapshot(
            root,
            path,
            new_oid,
            new_mode,
            after_limit,
            worktree=unstaged,
        )
        total += min(after_bytes, after_limit)
        if (before_error == "file_too_large" and before_limit < max_file_bytes) or (
            after_error == "file_too_large" and after_limit < max_file_bytes
        ):
            error = "total_byte_limit"
        error = error or before_error or after_error
        record = {
            "id": "diff:" + path,
            "relative_path": path,
            "path": str(root / path),
            "change": status,
            "before_mode": old_mode,
            "after_mode": new_mode,
            "before_blob": old_oid,
            "after_blob": new_oid if not unstaged else None,
            "before_sha256": before_hash,
            "after_sha256": after_hash,
            "evidence_complete": error is None,
            "text": json.dumps(
                {
                    "path": path,
                    "change": status,
                    "before_mode": old_mode,
                    "after_mode": new_mode,
                    "before": before_text,
                    "after": after_text,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        }
        if error:
            record["fetch_error"] = error
            errors.append({"id": record["id"], "error": error})
        records.append(record)
    incomplete = bool(errors or parse_error or len(changes) > limit or not command["ok"])
    return records, {
        "ok": command["ok"] and not parse_error,
        "root": str(root),
        "scope": scope,
        "before_commit": before,
        "after_commit": after,
        "before_source": "index" if unstaged else "commit",
        "after_source": "working_tree" if unstaged else "index" if staged else "commit",
        "candidate_limit_reached": len(changes) > limit,
        "truncated": incomplete,
        "file_errors": errors,
        "collected_bytes": total,
        "max_file_bytes": max_file_bytes,
        "change_fingerprint": hashlib.sha256(raw.encode()).hexdigest(),
        "diff_argv": args,
        "collection_error": command["stop_reason"] or ("git_failed" if not command["ok"] else None),
        "semantics": "full before/after per tracked changed file; renames represented as delete/add; untracked files excluded; no tests executed",
    }


def changed_diff_sources(records, collection):
    """Recheck the program-owned snapshot after inference; a changed scope needs review."""
    root = Path(collection["root"])
    raw, meta = _git(root, collection["diff_argv"])
    if (
        not meta["ok"]
        or hashlib.sha256(raw.encode()).hexdigest() != collection["change_fingerprint"]
    ):
        return [row["id"] for row in records]
    changed = []
    if collection["scope"] == "unstaged":
        for row in records:
            if not row["evidence_complete"]:
                continue
            _, digest, error, _ = _snapshot(
                root,
                row["relative_path"],
                "0" * 40,
                "100644",
                collection["max_file_bytes"],
                worktree=True,
            )
            if error or digest != row["after_sha256"]:
                changed.append(row["id"])
    return changed
