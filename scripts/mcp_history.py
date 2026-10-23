"""Read bounded, complete Actions history before allowing a new Registry submission."""

import io
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile

REPOSITORY = "apixly-ai/jev-filter"
SERVER = "io.github." + REPOSITORY
WORKFLOW = ".github/workflows/publish-mcp-registry.yml"
PREFLIGHT = "Verify exact npm publication and reconcile the Registry version"
PUBLISH = "Publish once and verify the exact Registry record"
MAX_RUNS = 100
MAX_ATTEMPTS = 10
MAX_ITEMS = 100
MAX_BYTES = 2_000_000
ARTIFACT_PREFIX = "mcp-registry-publication-state-"
ATTEMPT_STATUSES = {
    "submission_in_progress",
    "execution_uncertain",
    "published_verified",
    "already_published",
    "conflicting_registry_record",
}


class Page:
    def __init__(self, data, has_next=False):
        self.data = data
        self.has_next = has_next


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


class GitHubAPI:
    def __init__(self, token, opener=None):
        if not token:
            raise RuntimeError("A read-only GitHub Actions token is required for history")
        self.token = token
        self.base = "https://api.github.com/repos/" + REPOSITORY
        self.opener = opener or urllib.request.build_opener(NoRedirect())

    def _read(self, url, *, authenticated=False, allow_redirect=False):
        headers = {"User-Agent": "jev-filter-publication-history"}
        if authenticated:
            if not url.startswith(self.base + "/actions/"):
                raise RuntimeError("GitHub token is restricted to first-party Actions API reads")
            headers.update(
                {
                    "Authorization": "Bearer " + self.token,
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2026-03-10",
                }
            )
        if urllib.parse.urlsplit(url).scheme != "https":
            raise RuntimeError("GitHub artifact redirects must use HTTPS")
        request = urllib.request.Request(url, headers=headers)
        try:
            with self.opener.open(request, timeout=20) as response:
                body = response.read(MAX_BYTES + 1)
                link = response.headers.get("Link", "")
        except urllib.error.HTTPError as exc:
            if allow_redirect and exc.code in {301, 302, 303, 307, 308}:
                location = exc.headers.get("Location")
                if location:
                    return None, urllib.parse.urljoin(url, location), False
            raise RuntimeError(f"GitHub history request failed (HTTP {exc.code})") from None
        except (OSError, urllib.error.URLError):
            raise RuntimeError("GitHub history request failed; history is incomplete") from None
        if len(body) > MAX_BYTES:
            raise RuntimeError("GitHub history response exceeded its byte limit")
        return body, None, 'rel="next"' in link

    def json(self, path):
        body, _, has_next = self._read(self.base + path, authenticated=True)
        try:
            data = json.loads(body)
        except ValueError:
            raise RuntimeError("GitHub history returned unreadable JSON") from None
        if not isinstance(data, dict):
            raise RuntimeError("GitHub history returned an invalid object")
        return Page(data, has_next)

    def read_journal(self, artifact):
        body, redirect, _ = self._read(
            self.base + f"/actions/artifacts/{artifact['id']}/zip",
            authenticated=True,
            allow_redirect=True,
        )
        for _ in range(3):
            if redirect is None:
                break
            # Signed artifact storage URLs must never receive the GitHub bearer token.
            body, redirect, _ = self._read(redirect, allow_redirect=True)
        if body is None or redirect is not None:
            raise RuntimeError("GitHub journal download redirects are incomplete")
        try:
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                files = [entry for entry in archive.infolist() if not entry.is_dir()]
                if len(files) != 1 or files[0].filename != "mcp-publication-state.json":
                    raise ValueError
                if files[0].file_size > 100_000:
                    raise ValueError
                value = json.loads(archive.read(files[0]))
        except (ValueError, OSError, zipfile.BadZipFile, RuntimeError):
            raise RuntimeError("GitHub publication journal is unreadable") from None
        if not isinstance(value, dict):
            raise RuntimeError("GitHub publication journal is not an object")
        return value


def collection(page, key, limit=MAX_ITEMS):
    total = page.data.get("total_count")
    rows = page.data.get(key)
    if type(total) is not int or not 0 <= total < limit:
        raise RuntimeError("GitHub history reached its completeness limit")
    if page.has_next or not isinstance(rows, list) or len(rows) != total:
        raise RuntimeError("GitHub history pagination is incomplete")
    return rows


def started(step):
    return step.get("conclusion") != "skipped" and (
        step.get("started_at") is not None or step.get("status") in {"in_progress", "completed"}
    )


class GitHubHistory:
    def __init__(self, api, *, run_id, run_attempt):
        self.api = api
        self.run_id = run_id
        self.run_attempt = run_attempt

    @classmethod
    def from_env(cls):
        if os.environ.get("GITHUB_ACTIONS") != "true":
            return None
        if os.environ.get("GITHUB_REPOSITORY") != REPOSITORY:
            raise RuntimeError("Publication history must belong to the canonical repository")
        values = [os.environ.get(key, "") for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")]
        if not all(re.fullmatch(r"[1-9][0-9]*", value) for value in values):
            raise RuntimeError("GitHub publication run identity is incomplete")
        return cls(
            GitHubAPI(os.environ.get("GITHUB_TOKEN")),
            run_id=int(values[0]),
            run_attempt=int(values[1]),
        )

    def context(self):
        return {
            "journal_schema_version": 1,
            "github_run_id": self.run_id,
            "github_run_attempt": self.run_attempt,
            "workflow_path": WORKFLOW,
        }

    def _attempt(self, run, attempt, artifacts):
        page = self.api.json(
            f"/actions/runs/{run['id']}/attempts/{attempt}/jobs?per_page=100&page=1"
        )
        jobs = collection(page, "jobs")
        if (
            len(jobs) != 1
            or jobs[0].get("name") != "publish"
            or jobs[0].get("status") != "completed"
        ):
            raise RuntimeError("GitHub publication job history is incomplete")
        job = jobs[0]
        if job.get("conclusion") == "skipped":
            return None
        steps = job.get("steps", [])
        preflight = [step for step in steps if step.get("name") == PREFLIGHT]
        publication = [step for step in steps if step.get("name") == PUBLISH]
        if len(preflight) != 1 or len(publication) != 1:
            raise RuntimeError("GitHub publication step history is incomplete")
        was_started = started(publication[0])
        expected_name = f"{ARTIFACT_PREFIX}{run['id']}-{attempt}"
        matches = [artifact for artifact in artifacts if artifact.get("name") == expected_name]
        if not matches and not started(preflight[0]) and not was_started:
            return None  # GitHub conclusively records that neither publishing phase ran.
        if len(matches) != 1:
            raise RuntimeError("GitHub publication journal is missing or ambiguous")
        artifact = matches[0]
        size = artifact.get("size_in_bytes")
        if (
            artifact.get("expired") is not False
            or type(size) is not int
            or not 0 < size <= MAX_BYTES
            or type(artifact.get("id")) is not int
            or artifact["id"] <= 0
        ):
            raise RuntimeError("GitHub publication artifact is expired or unreadable")
        journal = self.api.read_journal(artifact)
        valid = (
            type(journal.get("journal_schema_version")) is int
            and journal["journal_schema_version"] == 1
            and type(journal.get("github_run_id")) is int
            and journal.get("github_run_id") == run["id"]
            and type(journal.get("github_run_attempt")) is int
            and journal.get("github_run_attempt") == attempt
            and journal.get("workflow_path") == WORKFLOW
            and journal.get("name") == SERVER
            and isinstance(journal.get("version"), str)
            and re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", journal["version"])
            and isinstance(journal.get("manifest_sha256"), str)
            and re.fullmatch(r"[a-f0-9]{64}", journal.get("manifest_sha256", ""))
            and type(journal.get("publish_attempts")) is int
            and journal["publish_attempts"] in {0, 1}
            and isinstance(journal.get("status"), str)
            and journal["status"] in ATTEMPT_STATUSES | {"checking", "ready"}
        )
        if not valid:
            raise RuntimeError("GitHub publication journal identity or state is invalid")
        journal["publication_started"] = was_started
        return journal

    def assert_clear(self, manifest):
        # GitHub reruns reuse the run ID with a fresh runner. Reconcile via the Registry
        # first; never start a new submission from any rerun attempt.
        if self.run_attempt != 1:
            raise RuntimeError(
                "GitHub workflow rerun cannot submit; use exact Registry reconciliation"
            )
        workflow = self.api.json("/actions/workflows/publish-mcp-registry.yml").data
        current = self.api.json(f"/actions/runs/{self.run_id}").data
        number = current.get("run_number")
        if (
            workflow.get("path") != WORKFLOW
            or current.get("id") != self.run_id
            or current.get("workflow_id") != workflow.get("id")
            or current.get("run_attempt") != self.run_attempt
            or type(number) is not int
            or not 0 < number < MAX_RUNS
        ):
            raise RuntimeError("GitHub workflow history identity or run limit is invalid")
        page = self.api.json(f"/actions/workflows/{workflow['id']}/runs?per_page=100&page=1")
        runs = collection(page, "workflow_runs", MAX_RUNS)
        prior = [
            run
            for run in runs
            if type(run.get("run_number")) is int and run["run_number"] <= number
        ]
        if (
            len(prior) != number
            or {run["run_number"] for run in prior} != set(range(1, number + 1))
            or len({run.get("id") for run in prior}) != number
            or not any(
                run.get("id") == self.run_id and run["run_number"] == number for run in prior
            )
        ):
            raise RuntimeError("GitHub numbered workflow history is incomplete")
        checked = 0
        for run in prior:
            if run["id"] == self.run_id:
                continue
            attempts = run.get("run_attempt")
            if (
                run.get("workflow_id") != workflow["id"]
                or run.get("status") != "completed"
                or type(attempts) is not int
                or not 0 < attempts < MAX_ATTEMPTS
            ):
                raise RuntimeError(
                    "GitHub prior attempt history is incomplete or reached its limit"
                )
            artifacts = collection(
                self.api.json(f"/actions/runs/{run['id']}/artifacts?per_page=100&page=1"),
                "artifacts",
            )
            for attempt in range(1, attempts + 1):
                journal = self._attempt(run, attempt, artifacts)
                checked += 1
                if journal is not None and (journal["name"], journal["version"]) == (
                    manifest["name"],
                    manifest["version"],
                ):
                    if (
                        journal["publication_started"]
                        or journal["publish_attempts"]
                        or journal["status"] in ATTEMPT_STATUSES
                    ):
                        raise RuntimeError(
                            "A previous Registry publication may have happened; submission is blocked"
                        )
        return {
            **self.context(),
            "history_runs_checked": number,
            "history_attempts_checked": checked,
        }
