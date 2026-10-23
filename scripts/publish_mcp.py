"""Gate manual Registry publication on exact npm identity and immutable-version readback."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REGISTRY = "https://registry.modelcontextprotocol.io/v0.1/servers/"
OFFICIAL = "io.modelcontextprotocol.registry/official"
SERVER = "io.github.apixly-ai/jev-filter"


def get_json(url, allow_missing=False):
    request = urllib.request.Request(url, headers={"User-Agent": "jev-filter-registry-publisher"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read(2_000_001)
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and allow_missing:
            return None
        raise RuntimeError(f"Public metadata lookup failed (HTTP {exc.code})") from None
    except (OSError, urllib.error.URLError):
        raise RuntimeError("Public metadata lookup failed; status remains unknown") from None
    if len(body) > 2_000_000:
        raise RuntimeError("Public metadata response exceeded the byte limit")
    try:
        data = json.loads(body)
    except ValueError:
        raise RuntimeError("Public metadata response was not valid JSON") from None
    if not isinstance(data, dict):
        raise RuntimeError("Public metadata response was not an object")
    return data


def registry_url(manifest):
    return (
        REGISTRY
        + urllib.parse.quote(manifest["name"], safe="")
        + "/versions/"
        + urllib.parse.quote(manifest["version"], safe="")
    )


def npm_lookup(manifest):
    package = manifest["packages"][0]
    return get_json(
        "https://registry.npmjs.org/"
        + urllib.parse.quote(package["identifier"], safe="")
        + "/"
        + urllib.parse.quote(package["version"], safe="")
    )


def registry_lookup(manifest):
    return get_json(registry_url(manifest), allow_missing=True)


def canonical(manifest):
    return {key: value for key, value in manifest.items() if key != "$schema"}


def verify_record(manifest, record):
    metadata = record.get("_meta")
    official = metadata.get(OFFICIAL) if isinstance(metadata, dict) else None
    status = official.get("status") if isinstance(official, dict) else None
    if status != "active":
        raise ValueError("Registry version is not active; review its existing status")
    server = record.get("server")
    if not isinstance(server, dict) or canonical(server) != canonical(manifest):
        raise ValueError("Registry contains different metadata for this immutable version")


def write_state(path, state):
    temporary = path.with_suffix(path.suffix + ".tmp")
    state["checked_at"] = datetime.now(timezone.utc).isoformat()
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def publish_manifest(
    manifest,
    *,
    npm_lookup=npm_lookup,
    registry_lookup=registry_lookup,
    submit=None,
    state_path,
    sleep=time.sleep,
):
    package = manifest["packages"][0]
    npm = npm_lookup(manifest)
    expected = (package["identifier"], package["version"], manifest["name"])
    if (npm.get("name"), npm.get("version"), npm.get("mcpName")) != expected:
        raise ValueError("Published npm name, version or mcpName does not match server.json")
    state_path = Path(state_path)
    previous = json.loads(state_path.read_text()) if state_path.exists() else {}
    state = {
        "name": manifest["name"],
        "version": manifest["version"],
        "manifest_sha256": hashlib.sha256(
            json.dumps(canonical(manifest), sort_keys=True).encode()
        ).hexdigest(),
        "registry_url": registry_url(manifest),
        "publish_attempts": 0,
    }
    existing = registry_lookup(manifest)
    if existing is not None:
        verify_record(manifest, existing)
        state.update(status="already_published", publish_needed=False)
        write_state(state_path, state)
        return state
    if (previous.get("name"), previous.get("version")) == (
        manifest["name"],
        manifest["version"],
    ) and previous.get("status") in {"submission_in_progress", "execution_uncertain"}:
        raise RuntimeError(
            "Previous Registry submission is unconfirmed; reconcile before publishing"
        )
    state.update(status="ready", publish_needed=True)
    write_state(state_path, state)
    if submit is None:
        return state
    state.update(status="submission_in_progress", publish_attempts=1, publish_needed=None)
    write_state(state_path, state)
    try:
        state["publisher_exit_code"] = submit()
    except Exception as exc:
        state.update(publisher_exit_code=None, publisher_error_type=type(exc).__name__)
    write_state(state_path, state)
    for attempt in range(6):
        try:
            record = registry_lookup(manifest)
        except RuntimeError:
            record = None
        if record is not None:
            try:
                verify_record(manifest, record)
            except ValueError:
                state["status"] = "conflicting_registry_record"
                write_state(state_path, state)
                raise
            state.update(status="published_verified", publish_needed=False)
            write_state(state_path, state)
            return state
        if attempt < 5:
            sleep(5)
    state["status"] = "execution_uncertain"
    write_state(state_path, state)
    raise RuntimeError("Registry publication is unconfirmed; reconcile before another attempt")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="server.json")
    parser.add_argument("--state", default="mcp-publication-state.json")
    parser.add_argument("--publish", metavar="PUBLISHER", help="Submit once with this trusted CLI")
    args = parser.parse_args()
    manifest_path = Path(args.manifest).resolve(strict=True)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    package = manifest.get("packages", [{}])[0]
    if (
        manifest.get("name") != SERVER
        or not re.fullmatch(
            r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", manifest.get("version", "")
        )
        or len(manifest.get("packages", [])) != 1
        or package.get("registryType") != "npm"
        or package.get("identifier") != "@apixly/jev-filter"
        or package.get("version") != manifest["version"]
        or package.get("transport") != {"type": "stdio"}
        or manifest.get("remotes")
    ):
        raise ValueError("Only the exact stable Jev Filter npm stdio manifest may be published")

    def submit():
        result = subprocess.run(
            [str(Path(args.publish).resolve(strict=True)), "publish", str(manifest_path)],
            capture_output=True,
            timeout=90,
            check=False,
        )
        return result.returncode

    result = publish_manifest(
        manifest, state_path=Path(args.state), submit=submit if args.publish else None
    )
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
            handle.write("publish_needed=" + str(result["publish_needed"]).lower() + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from None
