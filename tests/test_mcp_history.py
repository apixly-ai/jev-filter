"""Synthetic complete Actions history and token-isolated artifact reads; no network."""

import copy
import importlib.util
import io
import json
import urllib.error
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ".github/workflows/publish-mcp-registry.yml"
PREFLIGHT = "Verify exact npm publication and reconcile the Registry version"
PUBLISH = "Publish once and verify the exact Registry record"


@pytest.fixture
def history():
    spec = importlib.util.spec_from_file_location("mcp_history", ROOT / "scripts/mcp_history.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def manifest():
    return json.loads((ROOT / "server.json").read_text(encoding="utf-8"))


class FakeAPI:
    def __init__(self, manifest):
        self.next_pages = set()
        prior = {
            "id": 10,
            "run_number": 1,
            "run_attempt": 1,
            "workflow_id": 5,
            "status": "completed",
        }
        current = {
            "id": 20,
            "run_number": 2,
            "run_attempt": 1,
            "workflow_id": 5,
            "status": "in_progress",
        }
        self.documents = {
            "/actions/workflows/publish-mcp-registry.yml": {"id": 5, "path": WORKFLOW},
            "/actions/runs/20": current,
            "/actions/workflows/5/runs?per_page=100&page=1": {
                "total_count": 2,
                "workflow_runs": [current, prior],
            },
            "/actions/runs/10/attempts/1/jobs?per_page=100&page=1": {
                "total_count": 1,
                "jobs": [
                    {
                        "name": "publish",
                        "status": "completed",
                        "conclusion": "failure",
                        "steps": [
                            {"name": PREFLIGHT, "status": "completed", "conclusion": "success"},
                            {"name": PUBLISH, "status": "completed", "conclusion": "failure"},
                        ],
                    }
                ],
            },
            "/actions/runs/10/artifacts?per_page=100&page=1": {
                "total_count": 1,
                "artifacts": [
                    {
                        "id": 101,
                        "name": "mcp-registry-publication-state-10-1",
                        "expired": False,
                        "size_in_bytes": 1000,
                    }
                ],
            },
        }
        self.journals = {
            101: {
                "journal_schema_version": 1,
                "github_run_id": 10,
                "github_run_attempt": 1,
                "workflow_path": WORKFLOW,
                "name": manifest["name"],
                "version": manifest["version"],
                "manifest_sha256": "a" * 64,
                "status": "execution_uncertain",
                "publish_attempts": 1,
            }
        }

    def json(self, path):
        if path not in self.documents:
            raise RuntimeError("GitHub history is unavailable")
        return SimpleNamespace(
            data=copy.deepcopy(self.documents[path]), has_next=path in self.next_pages
        )

    def read_journal(self, artifact):
        if artifact["id"] not in self.journals:
            raise RuntimeError("GitHub journal is unreadable")
        return copy.deepcopy(self.journals[artifact["id"]])


def guard(history, api, attempt=1):
    return history.GitHubHistory(api, run_id=20, run_attempt=attempt)


def test_fresh_run_blocks_prior_uncertain_version(history, manifest):
    with pytest.raises(RuntimeError, match="previous.*publication"):
        guard(history, FakeAPI(manifest)).assert_clear(manifest)


def test_same_run_failed_job_rerun_fails_closed(history, manifest):
    with pytest.raises(RuntimeError, match="rerun"):
        guard(history, FakeAPI(manifest), attempt=2).assert_clear(manifest)


def test_missing_journal_after_publication_step_started_fails_closed(history, manifest):
    api = FakeAPI(manifest)
    api.documents["/actions/runs/10/artifacts?per_page=100&page=1"] = {
        "total_count": 0,
        "artifacts": [],
    }
    with pytest.raises(RuntimeError, match="journal"):
        guard(history, api).assert_clear(manifest)


def test_known_different_version_is_allowed(history, manifest):
    api = FakeAPI(manifest)
    api.journals[101]["version"] = "0.4.1"
    result = guard(history, api).assert_clear(manifest)
    assert result["history_runs_checked"] == 2 and result["history_attempts_checked"] == 1


def test_previously_published_but_now_absent_is_not_republished(history, manifest):
    api = FakeAPI(manifest)
    api.journals[101]["status"] = "published_verified"
    with pytest.raises(RuntimeError, match="previous.*publication"):
        guard(history, api).assert_clear(manifest)


@pytest.mark.parametrize("problem", ["gap", "limit", "truncated", "next_page"])
def test_incomplete_or_bounded_history_fails_closed(history, manifest, problem):
    api = FakeAPI(manifest)
    path = "/actions/workflows/5/runs?per_page=100&page=1"
    if problem == "gap":
        api.documents["/actions/runs/20"]["run_number"] = 3
    elif problem == "limit":
        api.documents[path]["total_count"] = history.MAX_RUNS
    elif problem == "truncated":
        api.documents[path]["workflow_runs"] = api.documents[path]["workflow_runs"][:1]
    else:
        api.next_pages.add(path)
    with pytest.raises(RuntimeError, match="history|limit|pagination"):
        guard(history, api).assert_clear(manifest)


@pytest.mark.parametrize(
    "problem", ["expired", "unreadable", "wrong_attempt", "unknown_version", "missing_hash"]
)
def test_lost_or_unbound_artifact_fails_closed(history, manifest, problem):
    api = FakeAPI(manifest)
    if problem == "expired":
        api.documents["/actions/runs/10/artifacts?per_page=100&page=1"]["artifacts"][0][
            "expired"
        ] = True
    elif problem == "unreadable":
        api.journals.clear()
    elif problem == "wrong_attempt":
        api.journals[101]["github_run_attempt"] = 2
    elif problem == "unknown_version":
        api.journals[101]["version"] = "unknown"
    else:
        api.journals[101]["manifest_sha256"] = None
    with pytest.raises(RuntimeError, match="journal|artifact"):
        guard(history, api).assert_clear(manifest)


def test_all_previous_run_attempts_must_be_readable(history, manifest):
    api = FakeAPI(manifest)
    api.documents["/actions/workflows/5/runs?per_page=100&page=1"]["workflow_runs"][1][
        "run_attempt"
    ] = 2
    api.journals[101]["version"] = "0.4.1"
    with pytest.raises(RuntimeError, match="history"):
        guard(history, api).assert_clear(manifest)


def test_fresh_runner_real_history_guard_never_submits(history, manifest, tmp_path):
    spec = importlib.util.spec_from_file_location(
        "publisher_history_e2e", ROOT / "scripts/publish_mcp.py"
    )
    publisher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publisher)
    calls = []
    with pytest.raises(RuntimeError, match="previous.*publication"):
        publisher.publish_manifest(
            manifest,
            npm_lookup=lambda _: {
                "name": manifest["packages"][0]["identifier"],
                "version": manifest["version"],
                "mcpName": manifest["name"],
            },
            registry_lookup=lambda _: None,
            history_guard=guard(history, FakeAPI(manifest)).assert_clear,
            submit=lambda: calls.append(True),
            state_path=tmp_path / "fresh-state.json",
        )
    assert calls == []


def test_github_token_is_not_forwarded_to_artifact_storage(history):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("mcp-publication-state.json", json.dumps({"status": "ready"}))
    requests = []

    class Response(io.BytesIO):
        headers = {}

    class Opener:
        def open(self, request, **kwargs):
            requests.append(request)
            if len(requests) == 1:
                raise urllib.error.HTTPError(
                    request.full_url,
                    302,
                    "redirect",
                    {"Location": "https://example.blob.core.windows.net/signed-artifact"},
                    None,
                )
            return Response(stream.getvalue())

    api = history.GitHubAPI("synthetic-github-token", opener=Opener())
    assert api.read_journal({"id": 101, "size_in_bytes": 1000}) == {"status": "ready"}
    assert requests[0].get_header("Authorization") == "Bearer synthetic-github-token"
    assert requests[1].get_header("Authorization") is None
