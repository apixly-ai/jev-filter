import contextlib
import hashlib
import io
import json
import subprocess
from unittest.mock import patch

import pytest

from jev_context import tools


def write_source(path, text):
    path.write_bytes(text.encode("utf-8"))


def git(root, *argv):
    return subprocess.run(
        ["git", "-C", str(root), *argv], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repository(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "Synthetic Fixture")
    git(tmp_path, "config", "user.email", "fixture@example.invalid")
    git(tmp_path, "config", "core.autocrlf", "false")
    git(tmp_path, "config", "commit.gpgsign", "false")
    git(tmp_path, "config", "core.hooksPath", str(tmp_path / ".git" / "no-fixture-hooks"))
    write_source(tmp_path / "policy.py", "def allowed(user):\n    return user.is_admin\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "synthetic baseline")
    return tmp_path


def test_query_recall_and_callers_preserve_exact_hit(tmp_path):
    write_source(
        tmp_path / "store.py",
        "def persist_token(token):\n    return write_disk(token) # exact_anchor\n\n"
        "def renew_session(token):\n    return persist_token(token)\n\n"
        "def refresh_credentials(secret):\n    return save_credentials(secret)\n\n"
        "def unrelated():\n    return 1\n",
    )
    rows, meta = tools.collect_code(
        tmp_path, "exact_anchor", query="refresh credentials", expand_callers=True
    )
    assert {row["symbol"] for row in rows} == {
        "persist_token",
        "renew_session",
        "refresh_credentials",
    }
    exact = next(row for row in rows if row["symbol"] == "persist_token")
    assert "exact" in exact["retrieval"]["channels"]
    caller = next(row for row in rows if row["symbol"] == "renew_session")
    assert caller["retrieval"]["call_clues"] == ["persist_token"]
    assert meta["retrieval"]["query"] == "refresh credentials"
    assert (
        meta["retrieval"]["call_resolution"] == "one-hop syntactic name clues, not resolved calls"
    )
    assert all(
        row["source_sha256"] == hashlib.sha256((tmp_path / "store.py").read_bytes()).hexdigest()
        for row in rows
    )


def test_recall_limit_prioritizes_exact_and_reports_incomplete(tmp_path):
    write_source(
        tmp_path / "x.py",
        'def anchor():\n    return "exact_anchor"\n\n'
        "def refresh_token():\n    return 1\n\n"
        "def refresh_session():\n    return 2\n",
    )
    rows, meta = tools.collect_code(tmp_path, "exact_anchor", limit=1, query="refresh")
    assert [row["symbol"] for row in rows] == ["anchor"]
    assert meta["candidate_limit_reached"]


def test_recall_file_limit_is_not_silent(tmp_path):
    for name in ("a.py", "b.py"):
        write_source(tmp_path / name, "def refresh_token():\n    return 1\n")
    _, meta = tools.collect_code(tmp_path, "absent", query="refresh", max_files=1)
    assert meta["retrieval"]["file_limit_reached"]
    assert meta["truncated"]


def test_diff_collects_complete_before_after_and_pinned_commits(repository):
    from jev_context.diff import collect_diff

    base = git(repository, "rev-parse", "HEAD")
    write_source(repository / "policy.py", "def allowed(user):\n    return True\n")
    git(repository, "add", ".")
    git(repository, "commit", "-qm", "synthetic changed policy")
    rows, meta = collect_diff(repository, base=base)
    assert meta["before_commit"] == base
    assert meta["after_commit"] == git(repository, "rev-parse", "HEAD")
    assert meta["ok"]
    assert rows[0]["change"] == "M"
    evidence = json.loads(rows[0]["text"])
    assert evidence["before"] == "def allowed(user):\n    return user.is_admin\n"
    assert evidence["after"] == "def allowed(user):\n    return True\n"
    assert rows[0]["before_sha256"] == hashlib.sha256(evidence["before"].encode()).hexdigest()
    assert rows[0]["evidence_complete"]


def test_diff_staged_does_not_include_unstaged_changes(repository):
    from jev_context.diff import collect_diff

    write_source(repository / "policy.py", "def allowed(user):\n    return user.active\n")
    git(repository, "add", ".")
    write_source(repository / "policy.py", "def allowed(user):\n    return True\n")
    staged, _ = collect_diff(repository, staged=True)
    unstaged, meta = collect_diff(repository, unstaged=True)
    assert meta["before_commit"] is None
    assert meta["before_source"] == "index"
    assert json.loads(staged[0]["text"])["after"].endswith("return user.active\n")
    assert json.loads(unstaged[0]["text"])["before"].endswith("return user.active\n")
    assert json.loads(unstaged[0]["text"])["after"].endswith("return True\n")


def test_diff_added_deleted_binary_and_overflow_are_preserved(repository):
    from jev_context.diff import collect_diff

    (repository / "policy.py").unlink()
    write_source(repository / "new.py", "added\n")
    (repository / "binary.dat").write_bytes(b"\x00\xff\x00")
    git(repository, "add", "-A")
    rows, meta = collect_diff(repository, staged=True)
    by_path = {row["relative_path"]: row for row in rows}
    assert json.loads(by_path["policy.py"]["text"])["after"] is None
    assert json.loads(by_path["new.py"]["text"])["before"] is None
    assert by_path["binary.dat"]["fetch_error"] == "binary_or_invalid_utf8"
    assert meta["truncated"]
    rows, meta = collect_diff(repository, staged=True, max_file_bytes=2)
    assert any(row.get("fetch_error") == "file_too_large" for row in rows)
    assert meta["truncated"]


def test_diff_rejects_unbounded_or_option_like_ranges(repository):
    from jev_context.diff import collect_diff

    with pytest.raises(ValueError):
        collect_diff(repository)
    with pytest.raises(ValueError):
        collect_diff(repository, base="--all")
    with pytest.raises(ValueError):
        collect_diff(repository, staged=True, unstaged=True)


def test_diff_revision_freshness_for_worktree(repository):
    from jev_context.diff import changed_diff_sources, collect_diff

    write_source(repository / "policy.py", "def allowed(user):\n    return True\n")
    rows, meta = collect_diff(repository, unstaged=True)
    assert changed_diff_sources(rows, meta) == []
    write_source(repository / "policy.py", "changed again\n")
    assert changed_diff_sources(rows, meta) == [rows[0]["id"]]


def test_diff_budget_is_bounded_and_preserves_all_failed_files(repository):
    from jev_context.diff import collect_diff

    for name in ("one.txt", "two.txt", "three.txt"):
        write_source(repository / name, "synthetic body\n" * 10)
    git(repository, "add", ".")
    rows, meta = collect_diff(repository, staged=True, max_total_bytes=3)
    assert len(rows) == 3
    assert all(row["fetch_error"] == "total_byte_limit" for row in rows)
    assert meta["collected_bytes"] <= 3
    assert meta["truncated"]


def test_diff_review_cli_rechecks_scope_after_analysis(repository):
    write_source(repository / "policy.py", "def allowed(user):\n    return True\n")

    def analyze(rows, *args):
        write_source(repository / "policy.py", "def allowed(user):\n    return False\n")
        return {
            "ok": True,
            "complete": True,
            "selected_ids": [rows[0]["id"]],
            "review_ids": [],
            "excerpts": [{"source_id": rows[0]["id"], "decision": "MATCH"}],
            "receipt": "fixture",
        }

    output = io.StringIO()
    with (
        patch("jev_context.tools.analyze_records", side_effect=analyze),
        contextlib.redirect_stdout(output),
    ):
        code = tools.main(
            [
                "diff-review",
                "--root",
                str(repository),
                "--unstaged",
                "--task",
                "Find weakened checks",
            ]
        )
    result = json.loads(output.getvalue())
    assert code == 2
    assert result["selected_ids"] == []
    assert result["review_ids"] == ["diff:policy.py"]
    assert result["changed_sources"] == ["diff:policy.py"]


def test_diff_commit_range_is_immutable_after_head_moves(repository):
    from jev_context.diff import changed_diff_sources, collect_diff

    base = git(repository, "rev-parse", "HEAD")
    write_source(repository / "policy.py", "def allowed(user):\n    return True\n")
    git(repository, "add", ".")
    git(repository, "commit", "-qm", "second synthetic commit")
    rows, meta = collect_diff(repository, base=base)
    write_source(repository / "policy.py", "later working tree\n")
    git(repository, "add", ".")
    git(repository, "commit", "-qm", "third synthetic commit")
    assert changed_diff_sources(rows, meta) == []


def test_diff_limit_and_symlink_do_not_claim_complete(repository):
    from jev_context.diff import collect_diff

    for name in ("a.txt", "b.txt"):
        write_source(repository / name, "body\n")
    git(repository, "add", ".")
    rows, meta = collect_diff(repository, staged=True, limit=1)
    assert len(rows) == 1
    assert meta["candidate_limit_reached"]
    (repository / "policy.py").unlink()
    try:
        (repository / "policy.py").symlink_to("a.txt")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    rows, _ = collect_diff(repository, unstaged=True)
    assert (
        next(r for r in rows if r["relative_path"] == "policy.py")["fetch_error"]
        == "symlink_not_followed"
    )


def test_recall_validation_and_partial_parser_failures(tmp_path):
    write_source(tmp_path / "bad.py", "def refresh(:\n pass\n")
    rows, meta = tools.collect_code(tmp_path, "absent", query="refresh")
    assert rows[0]["fetch_error"] == "parse_error"
    assert meta["truncated"]
    with pytest.raises(ValueError):
        tools.collect_code(tmp_path, "absent", query=" ")
    with pytest.raises(ValueError):
        tools.collect_code(tmp_path, "absent", query="refresh", max_files=0)


def test_recall_camelcase_and_single_file_scope(tmp_path):
    path = tmp_path / "handler.py"
    write_source(path, "def refreshCredentials():\n    return 1\n")
    rows, _ = tools.collect_code(path, "absent", query="refresh credentials")
    assert rows[0]["symbol"] == "refreshCredentials"


def test_triage_stdin_supports_structured_client_input():
    output = io.StringIO()

    def analyze(rows, *args):
        assert rows[0]["id"] == "correlated:synthetic"
        assert "ok" in rows[0]["text"]
        return {
            "ok": True,
            "complete": True,
            "selected_ids": [rows[0]["id"]],
            "review_ids": [],
            "excerpts": [],
            "receipt": "fixture",
        }

    with (
        patch("sys.stdin", io.StringIO('{"request_id":"synthetic","message":"ok"}\n')),
        patch("jev_context.tools.analyze_records", side_effect=analyze),
        contextlib.redirect_stdout(output),
    ):
        code = tools.main(["triage", "--input", "-", "--task", "Inspect synthetic event"])
    assert code == 0
    assert json.loads(output.getvalue())["selected_ids"] == ["correlated:synthetic"]


def test_diff_preserves_crlf_bytes_and_hashes(repository):
    from jev_context.diff import collect_diff

    raw = b"def allowed(user):\r\n    return True\r\n"
    (repository / "policy.py").write_bytes(raw)
    rows, _ = collect_diff(repository, unstaged=True)
    assert json.loads(rows[0]["text"])["after"].encode("utf-8") == raw
    assert rows[0]["after_sha256"] == hashlib.sha256(raw).hexdigest()


def test_diff_preserves_mode_only_changes(repository):
    from jev_context.diff import collect_diff

    git(repository, "update-index", "--chmod=+x", "policy.py")
    rows, _ = collect_diff(repository, staged=True)
    assert rows[0]["before_mode"] == "100644"
    assert rows[0]["after_mode"] == "100755"
    assert rows[0]["before_sha256"] == rows[0]["after_sha256"]
