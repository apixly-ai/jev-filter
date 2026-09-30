"""Run documented CLI flows end to end with synthetic data and real Jev calls."""

import argparse
import functools
import http.server
import json
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from .operations import Handler, api
from .scenarios import build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    target = Path(args.output)
    if target.exists():
        parser.error("Use a new output path")
    root = Path(__file__).resolve().parents[1]
    rows = []

    def run(name, arguments, stdin=None, expected=None, allowed=(0,)):
        started = time.perf_counter()
        call = subprocess.run(
            [sys.executable, "-I", "-m", "jev_filter", *arguments],
            input=stdin,
            text=True,
            capture_output=True,
        )
        payload = json.loads(call.stdout) if call.stdout.strip() else {}
        okay = call.returncode in allowed
        if expected is not None:
            okay = okay and set(payload.get("selected_ids", [])) == set(expected)
        info = payload if isinstance(payload, dict) else {}
        rows.append(
            {
                "name": name,
                "passed": okay,
                "exit_code": call.returncode,
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
                "selected_ids": info.get("selected_ids"),
                "review_ids": info.get("review_ids"),
                "usage": info.get("telemetry", {}).get("usage", info.get("usage")),
            }
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"complete": False, "rows": rows}, indent=2) + "\n", encoding="utf-8"
        )
        if not okay:
            raise RuntimeError("Tutorial failed: " + name)
        return payload

    with tempfile.TemporaryDirectory() as temp:
        base = Path(temp)
        build(base)
        run("doctor-live", ["doctor", "--live"])
        for locale in ("", ".zh-CN"):
            text = (root / f"docs/agent-quickstart{locale}.md").read_text(encoding="utf-8")
            spec = json.loads(re.search(r"```json\n(.*?)\n```", text, re.S)[1])
            records = json.loads(re.search(r"<<'JSON'\n(.*?)\nJSON", text, re.S)[1])
            config = base / "quickstart.json"
            config.write_text(json.dumps(spec), encoding="utf-8")
            run(
                "agent-quickstart" + locale,
                [
                    "query",
                    "--input",
                    "-",
                    "--analysis",
                    str(config),
                    "--task",
                    "Choose the export matching context.project and context.format",
                ],
                json.dumps(records),
                ["b"],
            )
            missing = {**spec, "context": {}}
            config.write_text(json.dumps(missing), encoding="utf-8")
            packet = run(
                "missing-context" + locale,
                [
                    "query",
                    "--input",
                    "-",
                    "--analysis",
                    str(config),
                    "--task",
                    "Choose matching export",
                ],
                json.dumps(records),
                allowed=(2,),
            )
            assert packet.get("missing_context")
        packet = run(
            "query-plan",
            [
                "query",
                "--input",
                str(root / "examples/candidates.json"),
                "--analysis",
                str(root / "examples/choose.json"),
                "--task",
                "Choose Beta JSON",
                "--plan",
            ],
        )
        assert packet["requests"] == 1 and not packet["deferred"]
        packet = run(
            "exec",
            [
                "exec",
                "--task",
                "Find current confirmed unresolved authentication-bypass release blockers",
                "--analysis",
                str(base / "command-analysis.json"),
                "--",
                sys.executable,
                "-c",
                "import sys;print(open(sys.argv[1]).read())",
                str(base / "command-records.json"),
            ],
            expected=["item-011", "item-052"],
        )
        run("list", ["list", packet["archive"]])
        run("read", ["read", packet["archive"], "--id", "item-011"])
        run(
            "triage",
            [
                "triage",
                "--input",
                str(base / "events.jsonl"),
                "--analysis",
                str(base / "triage-analysis.json"),
                "--task",
                "Find current network establishment failures before HTTP",
            ],
            expected=["correlated:req-013", "correlated:req-047"],
        )
        run(
            "code-search",
            [
                "code-search",
                "session",
                "--root",
                str(base / "code"),
                "--analysis",
                str(base / "code-analysis.json"),
                "--task",
                "Find functions writing a temporary session file and replacing the destination",
            ],
            expected=["session_store.py:persist_session:119"],
        )
        run(
            "search-plan",
            [
                "search",
                "os.replace",
                "--root",
                str(base / "code"),
                "--task",
                "Find the replacement call",
                "--plan",
            ],
        )
        requests = [
            {
                "id": "sample",
                "request": {
                    "model": "jev-1.13.0",
                    "state": "The light is red.",
                    "questions": {
                        "color": {
                            "type": "choice",
                            "instructions": "Select the observed color.",
                            "criteria": {"red": "Red", "green": "Green"},
                        }
                    },
                },
            }
        ]
        batch = run("typed-batch", ["batch", "--input", "-"], json.dumps(requests))
        assert batch["results"][0]["answers"]["color"]["choice"] == "red"
        server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), functools.partial(Handler, directory=str(base))
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
        origin = f"http://127.0.0.1:{server.server_port}"
        session = "jev-filter-tutorial"
        user = "camofox-" + session
        tab = None
        try:
            tab = api(
                "POST",
                "/tabs",
                {"userId": user, "sessionKey": "tutorial", "url": origin + "/page.html"},
            )["tabId"]
            packet = run(
                "locate",
                [
                    "locate",
                    "--session",
                    session,
                    "--tab",
                    tab,
                    "--origin",
                    origin,
                    "--task",
                    "Choose the enabled audit-record JSON export for the current project only",
                ],
                expected=["13"],
            )
            assert packet["target_guard"]["ok"] and packet["target_guard"]["dom_id"] == "target"
        finally:
            if tab:
                api("DELETE", f"/tabs/{tab}", {"userId": user})
            server.shutdown()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "complete": True,
                "scope": "Documented CLI/agent examples with synthetic inputs and live Jev. Missing-context and plan checks make no inference. No browser action or customer message.",
                "rows": rows,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"passed": len(rows), "failed": 0}))


if __name__ == "__main__":
    main()
