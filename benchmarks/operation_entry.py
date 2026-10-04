"""Single fixed collector invoked by the primary agent; raw arm is evaluation-only."""

import json
import subprocess
import sys
from pathlib import Path

from jev_context import tools
from jev_context.command import collect_command


def main():
    config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    base = Path(config["base"])
    case = config["case"]
    if config["arm"] == "filtered":
        command = [
            sys.executable,
            "-I",
            "-m",
            "jev_filter",
            case,
            "--task",
            config["task"],
            "--workers",
            str(config.get("jev_workers", 4)),
        ]
        if case == "code-search":
            command += [
                "session",
                "--root",
                str(base / "code"),
                "--analysis",
                str(base / "code-analysis.json"),
            ]
        elif case == "triage":
            command += [
                "--input",
                str(base / "events.jsonl"),
                "--analysis",
                str(base / "triage-analysis.json"),
            ]
        elif case == "exec":
            command += [
                "--analysis",
                str(base / "command-analysis.json"),
                "--",
                sys.executable,
                "-c",
                "import sys;print(open(sys.argv[1]).read())",
                str(base / "command-records.json"),
            ]
        else:
            command += [
                "--session",
                config["session"],
                "--tab",
                config["tab"],
                "--origin",
                config["origin"],
            ]
        return subprocess.run(command).returncode
    if case == "code-search":
        records, meta = tools.collect_code(base / "code", "session")
    elif case == "triage":
        records, meta = tools.collect_logs((base / "events.jsonl").read_text(encoding="utf-8"))
    elif case == "exec":
        records, meta = collect_command(
            [
                sys.executable,
                "-c",
                "import sys;print(open(sys.argv[1]).read())",
                str(base / "command-records.json"),
            ],
            split="json",
        )
    else:
        observed = tools.browser_call(
            config["session"],
            config["tab"],
            {"origin": config["origin"], "scope": "body", "limit": 200},
        )
        Path(config["observation"]).write_text(json.dumps(observed), encoding="utf-8")
        records = [tools.safe_control(r) for r in observed["records"] if r["enabled"]]
        meta = {k: v for k, v in observed.items() if k != "records"}
    print(
        json.dumps(
            {"records": records, "collection": meta}, ensure_ascii=False, separators=(",", ":")
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
