"""Real CLI/Python/JavaScript/MCP interface E2E with isolated synthetic data.

No API calls: explicit missing-context, planning and passthrough contracts are used.
Use --official-mcp after separately installing mcp to test an independent MCP client.
This checks interfaces and packaging; it does not measure semantic model quality.
"""

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def execute(command, *, cwd, env, input=None, exits=(0,)):
    result = subprocess.run(
        command, cwd=cwd, env=env, input=input, capture_output=True, text=True, timeout=60
    )
    if result.returncode not in exits:
        raise RuntimeError("e2e_command_failed")
    return json.loads(result.stdout)


async def official_mcp(cli, workspace, env):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async with stdio_client(
        StdioServerParameters(command=cli, args=["mcp", "--root", str(workspace)], env=env)
    ) as (read, write):
        async with ClientSession(read, write) as session:
            initialized = await session.initialize()
            tools = await session.list_tools()
            response = await session.call_tool(
                "filter_records",
                {
                    "task": "Synthetic current failure",
                    "records": [{"id": "x", "text": "Synthetic failure"}],
                    "analysis": {"required_context": ["deployment"]},
                },
            )
            packet = response.structuredContent
            assert packet["review_ids"] == ["x"] and not packet["complete"]
            recovered = await session.call_tool(
                "read_evidence", {"archive": packet["archive"], "id": "x"}
            )
            assert recovered.structuredContent["text"] == "Synthetic failure"
            return {
                "protocol": initialized.protocolVersion,
                "tools": len(tools.tools),
                "review_and_evidence_roundtrip": True,
            }


def run(cli, official=False):
    checks = []
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="jev-release-e2e-") as temporary:
        base = Path(temporary)
        env = {**os.environ, "JEV_STATS_DISABLED": "1", "JEV_STATS_DIR": str(base / "stats")}
        code = base / "workspace"
        code.mkdir()
        source = code / "sample.py"
        source.write_text("def sample():\n    return 'needle'\n", encoding="utf-8")
        spec = base / "analysis.json"
        spec.write_text(json.dumps({"required_context": ["deployment"]}), encoding="utf-8")
        passthrough = base / "passthrough.json"
        passthrough.write_text(json.dumps({"mode": "passthrough"}), encoding="utf-8")
        doctor = execute([cli, "doctor"], cwd=base, env=env)
        assert doctor["ok"] and doctor["ripgrep"]
        checks.append(
            {"name": "installed_cli_doctor", "passed": True, "version": doctor["version"]}
        )
        query = execute(
            [cli, "query", "--input", "-", "--task", "Current failure", "--analysis", str(spec)],
            cwd=base,
            env=env,
            input=json.dumps([{"id": "x", "text": "Synthetic failure"}]),
            exits=(2,),
        )
        assert query["complete"] is False
        checks.append({"name": "cli_context_admission", "passed": True})
        code_result = execute(
            [
                cli,
                "code-search",
                "needle",
                "--root",
                str(code),
                "--task",
                "Find handler",
                "--analysis",
                str(passthrough),
            ],
            cwd=base,
            env=env,
            exits=(0, 2),
        )
        assert code_result["ok"] and code_result["telemetry"]["requests"] == 0
        checks.append({"name": "cli_code_collection", "passed": True})
        triage = execute(
            [
                cli,
                "triage",
                "--input",
                "-",
                "--task",
                "Find failures",
                "--analysis",
                str(passthrough),
            ],
            cwd=base,
            env=env,
            input=json.dumps(
                {"request_id": "r1", "message": "Failure", "api_key": "synthetic-hidden-key"}
            ),
            exits=(0, 2),
        )
        assert triage["ok"] and "synthetic-hidden-key" not in json.dumps(triage)
        checks.append({"name": "cli_stdin_triage_redaction", "passed": True})
        for args in (
            ["init", "-q"],
            ["config", "user.name", "Synthetic fixture"],
            ["config", "user.email", "fixture@example.test"],
            ["config", "core.autocrlf", "false"],
            ["config", "commit.gpgsign", "false"],
            ["config", "core.hooksPath", str(base / "no-hooks")],
            ["add", "sample.py"],
            ["commit", "-qm", "fixture"],
        ):
            subprocess.run(["git", *args], cwd=code, env=env, capture_output=True, check=True)
        source.write_text("def sample():\n    return 'changed needle'\n", encoding="utf-8")
        diff = execute(
            [
                cli,
                "diff-review",
                "--root",
                str(code),
                "--unstaged",
                "--task",
                "Find changed behavior",
                "--analysis",
                str(passthrough),
            ],
            cwd=base,
            env=env,
            exits=(0, 2),
        )
        assert diff["ok"] and diff["telemetry"]["requests"] == 0
        checks.append({"name": "cli_complete_diff", "passed": True})
        survey = base / "survey.json"
        survey.write_text(
            json.dumps(
                {
                    "task": "Classify synthetic tickets",
                    "questions": {
                        "failure": {"type": "noul", "instructions": "The record reports a failure."}
                    },
                }
            ),
            encoding="utf-8",
        )
        records = base / "records.jsonl"
        records.write_text(
            json.dumps({"id": "x", "text": "Synthetic failure"}) + "\n", encoding="utf-8"
        )
        survey_result = execute(
            [cli, "survey", "--input", str(records), "--spec", str(survey), "--dry-run"],
            cwd=base,
            env=env,
        )
        assert survey_result
        checks.append({"name": "cli_survey_plan", "passed": True})
        evaluation = execute(
            [cli, "eval", "--input", str(ROOT / "examples/evaluation.json")], cwd=base, env=env
        )
        assert (
            evaluation["evaluation_usage"]["requests"] == 0 and evaluation["holdout"]["failed"] == 1
        )
        checks.append({"name": "cli_heldout_evaluation", "passed": True})
        requests = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-11-25"},
            },
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "filter_records",
                    "arguments": {"task": "Synthetic task", "records": []},
                },
            },
        ]
        wire = subprocess.run(
            [cli, "mcp", "--root", str(code)],
            input="\n".join(json.dumps(r) for r in requests) + "\n",
            cwd=base,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        responses = [json.loads(line) for line in wire.stdout.splitlines()]
        assert len(responses[1]["result"]["tools"]) == 4 and not responses[2]["result"]["isError"]
        checks.append({"name": "mcp_stdio_process", "passed": True})
        script = "const {createClient}=require(process.argv[1]);const client=createClient({command:[process.argv[2]]});client.query([{id:'x',text:'Synthetic failure'}],{task:'Current failure',analysis:{required_context:['deployment']}}).then(r=>{if(r.exitCode!==2||r.packet.complete!==false)process.exit(1);console.log(JSON.stringify({passed:true,partial_preserved:true}));}).catch(()=>process.exit(1));"
        js = execute(
            ["node", "-e", script, str(ROOT / "npm/client/index.cjs"), cli], cwd=base, env=env
        )
        checks.append({"name": "javascript_real_cli", **js})
        if official:
            checks.append(
                {
                    "name": "official_mcp_client",
                    "passed": True,
                    **asyncio.run(official_mcp(cli, code, env)),
                }
            )
    return {
        "schema_version": 1,
        "kind": "offline_real_interface_e2e",
        "version": doctor["version"],
        "checks": checks,
        "passed": all(c["passed"] for c in checks),
        "elapsed_ms": round((time.perf_counter() - started) * 1000),
        "actual_model_usage": {"requests": 0, "input_tokens": 0, "output_tokens": 0},
        "scope": "Real process/interface checks on synthetic data; no semantic inference, primary-agent continuation or external business action.",
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", default=str(Path(sys.executable).parent / "jev-filter"))
    parser.add_argument("--official-mcp", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        parser.error("output exists; preserve earlier evidence")
    result = run(str(Path(args.cli).resolve()), args.official_mcp)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "passed": result["passed"],
                "checks": len(result["checks"]),
                "elapsed_ms": result["elapsed_ms"],
            }
        )
    )
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
