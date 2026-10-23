"""Offline Registry publication gates, immutable-version reconciliation and uncertainty."""

import copy
import importlib.util
import json
import urllib.error
import urllib.parse
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def publisher():
    spec = importlib.util.spec_from_file_location("publish_mcp", ROOT / "scripts/publish_mcp.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def manifest():
    return json.loads((ROOT / "server.json").read_text(encoding="utf-8"))


def npm_record(manifest):
    package = manifest["packages"][0]
    return {
        "name": package["identifier"],
        "version": package["version"],
        "mcpName": manifest["name"],
    }


def registry_record(manifest, status="active"):
    return {
        "server": copy.deepcopy(manifest),
        "_meta": {"io.modelcontextprotocol.registry/official": {"status": status}},
    }


def test_identical_existing_version_skips_without_submission(publisher, manifest, tmp_path):
    calls = []
    result = publisher.publish_manifest(
        manifest,
        npm_lookup=lambda _: pytest.fail("active exact Registry record must reconcile first"),
        registry_lookup=lambda _: registry_record(manifest),
        history_guard=lambda _: pytest.fail("reconciliation must not depend on retained history"),
        submit=lambda: calls.append(True),
        state_path=tmp_path / "state.json",
    )
    assert result["status"] == "already_published" and not result["publish_needed"]
    assert calls == []


@pytest.mark.parametrize("field", ["name", "version", "mcpName"])
def test_npm_identity_mismatch_stops_before_submission(publisher, manifest, tmp_path, field):
    npm = npm_record(manifest)
    npm[field] = "unexpected"
    calls = []
    with pytest.raises(ValueError, match="npm"):
        publisher.publish_manifest(
            manifest,
            npm_lookup=lambda _: npm,
            registry_lookup=lambda _: None,
            submit=lambda: calls.append(True),
            state_path=tmp_path / "state.json",
        )
    assert calls == []


@pytest.mark.parametrize("conflict", ["description", "status", "malformed_status"])
def test_existing_conflict_or_inactive_record_is_not_overwritten(
    publisher, manifest, tmp_path, conflict
):
    record = registry_record(manifest)
    if conflict == "status":
        record["_meta"]["io.modelcontextprotocol.registry/official"]["status"] = "deleted"
    elif conflict == "malformed_status":
        record["_meta"] = []
    else:
        record["server"]["description"] = "A different immutable version"
    calls = []
    with pytest.raises(ValueError, match="Registry"):
        publisher.publish_manifest(
            manifest,
            npm_lookup=lambda _: npm_record(manifest),
            registry_lookup=lambda _: record,
            submit=lambda: calls.append(True),
            state_path=tmp_path / "state.json",
        )
    assert calls == []


def test_submission_intent_is_durable_and_delayed_readback_does_not_resubmit(
    publisher, manifest, tmp_path
):
    path = tmp_path / "state.json"
    reads = []
    submits = []

    def lookup(_):
        reads.append(True)
        return registry_record(manifest) if len(reads) >= 4 else None

    def submit():
        assert json.loads(path.read_text())["status"] == "submission_in_progress"
        submits.append(True)
        return 0

    result = publisher.publish_manifest(
        manifest,
        npm_lookup=lambda _: npm_record(manifest),
        registry_lookup=lookup,
        history_guard=lambda _: None,
        submit=submit,
        state_path=path,
        sleep=lambda _: None,
    )
    assert result["status"] == "published_verified"
    assert submits == [True]


def test_unconfirmed_submission_is_recorded_and_never_retried(publisher, manifest, tmp_path):
    path = tmp_path / "state.json"
    calls = []

    def submit():
        calls.append(True)
        raise OSError("synthetic transport failure")

    with pytest.raises(RuntimeError, match="unconfirmed"):
        publisher.publish_manifest(
            manifest,
            npm_lookup=lambda _: npm_record(manifest),
            registry_lookup=lambda _: None,
            history_guard=lambda _: None,
            submit=submit,
            state_path=path,
            sleep=lambda _: None,
        )
    state = json.loads(path.read_text())
    assert state["status"] == "execution_uncertain" and state["publish_attempts"] == 1
    assert state["publish_needed"] is None
    assert calls == [True]
    with pytest.raises(RuntimeError, match="Previous"):
        publisher.publish_manifest(
            manifest,
            npm_lookup=lambda _: npm_record(manifest),
            registry_lookup=lambda _: None,
            history_guard=lambda _: None,
            submit=submit,
            state_path=path,
            sleep=lambda _: None,
        )
    assert calls == [True]


def test_network_error_is_not_absence(publisher, monkeypatch):
    def fail(request, **kwargs):
        raise urllib.error.HTTPError(request.full_url, 403, "denied", {}, None)

    monkeypatch.setattr(publisher.urllib.request, "urlopen", fail)
    with pytest.raises(RuntimeError, match="HTTP 403"):
        publisher.get_json("https://example.invalid/record", allow_missing=True)


def test_exact_version_path_escapes_namespace_slash(publisher, manifest):
    url = publisher.registry_url(manifest)
    assert "/io.github.apixly-ai%2Fjev-filter/versions/" in url
    parsed = urllib.parse.urlsplit(url)
    assert parsed.path.endswith("/versions/" + manifest["version"])
    assert urllib.parse.parse_qs(parsed.query) == {"include_deleted": ["true"]}


def test_history_failure_stops_fresh_runner_before_submission(publisher, manifest, tmp_path):
    calls = []

    def history_guard(_):
        raise RuntimeError("previous publication remains uncertain")

    with pytest.raises(RuntimeError, match="previous publication"):
        publisher.publish_manifest(
            manifest,
            npm_lookup=lambda _: npm_record(manifest),
            registry_lookup=lambda _: None,
            history_guard=history_guard,
            submit=lambda: calls.append(True),
            state_path=tmp_path / "fresh-runner-state.json",
        )
    assert calls == []


def test_registry_publisher_subprocess_has_no_github_token(publisher, tmp_path, monkeypatch):
    binary = tmp_path / "publisher"
    binary.write_text("synthetic")
    manifest = tmp_path / "server.json"
    manifest.write_text("{}")
    monkeypatch.setenv("GITHUB_TOKEN", "synthetic-github-token")
    monkeypatch.setenv("GH_TOKEN", "synthetic-gh-token")
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(publisher.subprocess, "run", run)
    assert publisher.submit_once(binary, manifest) == 0
    assert "GITHUB_TOKEN" not in calls[0][1]["env"]
    assert "GH_TOKEN" not in calls[0][1]["env"]
