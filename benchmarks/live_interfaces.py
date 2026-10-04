"""Paid interface E2E using synthetic inputs and a fresh published npm installation.

Runs real Python processes, the published JS adapter/native binary, an independent
official MCP client, local browser extraction and a 64-record CLI survey. No cache.
Credentials are inherited only through the process environment and are never archived.
"""

import argparse
import asyncio
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from jev_context import __version__

from .fixture import SPEC, TASK, VARIANTS, fixture
from .live_records import (
    CODE_CONTEXT,
    CODE_TASKS,
    DIFF_CONTEXT,
    DIFF_EXPECTED,
    DIFF_FILES,
    DIFF_TASK,
)
from .retrieval import FILES

MODEL = "jev-1.13.0"
NPM_PACKAGE = "@apixly/jev-filter@0.4.0"
TOPICS = {
    "billing": "Charges, refunds, invoices and payments.",
    "bug": "Broken product behavior, crashes, errors or malfunctions.",
    "feature_request": "Requests new product functionality.",
    "account": "Login, account settings or account access.",
    "shipping": "Delivery, tracking or transit damage.",
    "other": "None of those topics.",
}
SURVEY_SPEC = {
    "task": "Classify the primary topic of each synthetic support ticket.",
    "model": MODEL,
    "questions": {
        "topic": {
            "type": "choice",
            "instructions": "What is the main topic of this support ticket?",
            "criteria": TOPICS,
        }
    },
    "group_by": ["topic"],
    "batch_size": 16,
    "confidence_floor": 0.6,
}
OFFERS = [
    ("L1", "Lamp", "In stock", 29, "USB-C charging"),
    ("L2", "Lamp", "Out of stock", 19, "USB-C charging"),
    ("L3", "Lamp", "In stock", 49, "USB-C charging"),
    ("L4", "Lamp", "In stock", 31, "USB-C charging"),
    ("L5", "Lamp", "In stock", 23, "AC powered"),
    ("L6", "Speaker", "In stock", 25, "USB-C charging"),
    ("L7", "Lamp", "In stock", 34, "USB-C charging"),
    ("L8", "Lamp", "In stock", 20, "USB-A charging"),
]
EXTRACT_SPEC = {
    "model": MODEL,
    "requirements": [
        {"id": "lamp", "statement": "The product in this row is a lamp.", "expected": True},
        {"id": "stock", "statement": "The product in this row is in stock.", "expected": True},
        {"id": "usbc", "statement": "The product supports USB-C charging.", "expected": True},
    ],
}
JS_SCRIPT = """
const fs=require('node:fs');
const payload=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));
const {createClient}=require(payload.module);
const client=createClient({cwd:payload.cwd});
const options={...payload.options,workers:4};
const methods={query:()=>client.query(payload.records,options),
 codeSearch:()=>client.codeSearch(payload.pattern,options),
 triage:()=>client.triage(payload.events,options),
 diffReview:()=>client.diffReview(options)};
methods[payload.method]().then(r=>console.log(JSON.stringify(r))).catch(e=>{
 console.log(JSON.stringify({failed:true,error:e.code||'adapter_failed'}));process.exitCode=2;
});
"""


def survey_fixture():
    variants = [
        ("billing", "I was charged twice this month. Please refund the duplicate payment."),
        ("billing", "这个月账单重复扣费，请退款。"),
        ("bug", "The app crashes every time I open settings."),
        ("bug", "升级后应用一打开设置就闪退。"),
        ("feature_request", "Please add a CSV export feature."),
        ("account", "I cannot log in; please unlock my account."),
        ("shipping", "The courier delivered my order to the wrong address."),
        ("other", "Hello support team. Have a pleasant day!"),
    ]
    records = [{"id": f"ticket-{i:03}", "text": variants[i % len(variants)][1]} for i in range(64)]
    labels = [
        {"id": row["id"], "topic": variants[i % len(variants)][0]} for i, row in enumerate(records)
    ]
    return records, labels, dict(Counter(row["topic"] for row in labels))


def extract_price_filter(skus, prices=None):
    prices = {row[0]: row[3] for row in OFFERS} if prices is None else prices
    return sorted(sku for sku in skus if prices[sku] < 35)


def usage_snapshot(packet):
    stats = packet.get("telemetry", packet)
    usage = stats.get("usage", {})
    counts = {
        key: usage.get(key) if type(usage.get(key)) is int and usage[key] >= 0 else None
        for key in ("input_tokens", "output_tokens")
    }
    return {
        "known_usage": counts,
        "usage_complete": stats.get("usage_complete") is True
        and all(value is not None for value in counts.values()),
        "requests": stats.get("requests"),
        "unknown_usage_attempts": stats.get("unknown_usage_attempts"),
        "requested_model": MODEL,
        "resolved_model": None,
        "resolved_model_basis": "This interface does not expose the provider response model; requested identity is not substituted for observed identity.",
    }


def public_packet(value, key=None):
    """Preserve complete synthetic outputs while replacing machine-specific receipts/paths."""
    if isinstance(value, dict):
        return {name: public_packet(child, name) for name, child in value.items()}
    if isinstance(value, list):
        return [public_packet(child, key) for child in value]
    if isinstance(value, str):
        if key in {"archive", "receipt", "analysis_receipt", "raw_archive"}:
            return "receipt:" + hashlib.sha256(value.encode()).hexdigest()[:16]
        if key in {"path", "root"} and Path(value).is_absolute():
            return Path(value).name
        return re.sub(r"127\.0\.0\.1:\d+", "127.0.0.1:PORT", value)
    return value


def execute(command, *, cwd, env, input=None, timeout=120):
    process = subprocess.run(
        command, cwd=cwd, env=env, input=input, capture_output=True, text=True, timeout=timeout
    )
    if process.returncode not in (0, 2):
        raise RuntimeError(f"process_exit_{process.returncode}")
    result = json.loads(process.stdout)
    return result, process.returncode, len(process.stdout.encode())


def query_inputs():
    parts, expected = fixture(32)
    return [{"id": row["id"], "text": row["text"]} for row in parts], expected


def events_fixture():
    events = [
        {"request_id": f"request-{i}", "message": text} for i, (_, text) in enumerate(VARIANTS)
    ]
    expected = [f"correlated:request-{i}" for i, (positive, _) in enumerate(VARIANTS) if positive]
    return events, expected


def code_spec():
    return {
        "model": MODEL,
        "context": CODE_CONTEXT,
        "required_context": ["fixture_facts"],
        "requirements": [
            {
                "id": "implements",
                "statement": "The target function meets the concrete selection and exclusion criteria stated in the task.",
                "expected": True,
            }
        ],
    }


def diff_spec():
    return {
        "model": MODEL,
        "context": DIFF_CONTEXT,
        "required_context": ["fixture_facts"],
        "requirements": [
            {
                "id": "weakens",
                "statement": "The target file change weakens authorization, input sanitization, a balance check or a behavioral test assertion compared with its before source.",
                "expected": True,
            }
        ],
    }


def check_selection(packet, expected, *, symbols=False):
    selected = packet.get("selected_ids", [])
    selected = [value.split(":")[1] for value in selected] if symbols else selected
    return {
        "passed": packet.get("ok") is True
        and packet.get("complete") is True
        and set(selected) == set(expected)
        and not packet.get("review_ids"),
        "selected": sorted(selected),
        "expected": sorted(expected),
        "false_positive": sorted(set(selected) - set(expected)),
        "false_negative": sorted(set(expected) - set(selected)),
    }


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def setup_diff(root, env):
    root.mkdir()
    for args in (
        ["init", "-q"],
        ["config", "user.name", "Synthetic Fixture"],
        ["config", "user.email", "fixture@example.invalid"],
        ["config", "commit.gpgsign", "false"],
        ["config", "core.autocrlf", "false"],
        ["config", "core.hooksPath", str(root / ".git/no-hooks")],
    ):
        subprocess.run(["git", *args], cwd=root, env=env, capture_output=True, check=True)
    files = dict(list(DIFF_FILES.items())[:6])
    for name, (before, _) in files.items():
        (root / name).write_text(before, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, env=env, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "synthetic baseline"],
        cwd=root,
        env=env,
        capture_output=True,
        check=True,
    )
    for name, (_, after) in files.items():
        (root / name).write_text(after, encoding="utf-8")
    return [f"diff:{name}" for name in files if DIFF_EXPECTED[name] == "MATCH"]


def benchmark(*, live=False, cli=None):
    cases = []
    result = {
        "schema_version": 1,
        "kind": "live_synthetic_interface_e2e" if live else "offline_live_interface_plan",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python_source_version": __version__,
        "npm_package": NPM_PACKAGE,
        "result_cache": False,
        "max_independent_workers": 4,
        "scope": "Real Python CLI and freshly installed published JS/native/MCP interfaces, local Chromium extraction and synthetic CLI survey. Whole process startup and verification included. No external business actions or primary-agent continuation.",
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "fixture_sha256": hashlib.sha256(
            json.dumps(
                {
                    "query": query_inputs(),
                    "events": events_fixture(),
                    "code": FILES,
                    "diff": list(DIFF_FILES.items())[:6],
                    "survey": survey_fixture(),
                    "offers": OFFERS,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest(),
        "limitations": [
            "Small synthetic interface checks are not a production reliability or open-web success study.",
            "Resolved model identity is unavailable from these public interfaces; requested model and returned token envelopes are kept separate.",
            "Survey repetitions cover eight simple templates, not a held-out topic-generalization evaluation.",
            "USD estimates in interface packets are application estimates, not verified supplier invoices.",
        ],
        "checks": cases,
    }
    if not live:
        return result
    cli = cli or str(Path(sys.executable).parent / "jev-filter")
    with tempfile.TemporaryDirectory(prefix="jev-paid-interfaces-") as temporary:
        base = Path(temporary)
        env = {**os.environ, "JEV_STATS_DISABLED": "1", "JEV_STATS_DIR": str(base / "stats")}
        code = base / "code"
        code.mkdir()
        for name, source in FILES.items():
            (code / name).write_text(source, encoding="utf-8")
        records, query_expected = query_inputs()
        events, triage_expected = events_fixture()
        specs = {
            "query": write_json(base / "query-spec.json", {**SPEC, "model": MODEL}),
            "code": write_json(base / "code-spec.json", code_spec()),
            "diff": write_json(base / "diff-spec.json", diff_spec()),
            "extract": write_json(base / "extract-spec.json", EXTRACT_SPEC),
        }
        diff_root = base / "diff"
        diff_expected = setup_diff(diff_root, env)

        def add(name, runner, validator):
            started = time.perf_counter()
            packet, exit_code, output_bytes = {}, None, None
            try:
                packet, exit_code, output_bytes = runner()
                verified = validator(packet)
                outcome = {
                    "name": name,
                    "exit_code": exit_code,
                    "verification": verified,
                    "passed": bool(verified["passed"]),
                }
            except Exception as error:
                outcome = {
                    "name": name,
                    "exit_code": exit_code,
                    "passed": False,
                    "error_type": type(error).__name__,
                    "error": str(error)
                    if isinstance(error, RuntimeError) and str(error).startswith("process_exit_")
                    else "interface_or_verification_failed",
                }
            outcome.update(
                whole_operation_ms=round((time.perf_counter() - started) * 1000, 3),
                returned_context_bytes=output_bytes,
                model_usage=usage_snapshot(packet),
                packet=public_packet(packet),
            )
            cases.append(outcome)
            return outcome

        def python_runner(arguments, input=None):
            return lambda: execute([cli, *arguments], cwd=base, env=env, input=input)

        common = ["--workers", "4", "--budget-chars", "12000"]
        add(
            "python_cli_query_32",
            python_runner(
                [
                    "query",
                    "--input",
                    "-",
                    "--task",
                    TASK,
                    "--analysis",
                    str(specs["query"]),
                    *common,
                ],
                json.dumps(records),
            ),
            lambda packet: check_selection(packet, query_expected),
        )
        add(
            "python_cli_code_recall",
            python_runner(
                [
                    "code-search",
                    "token_anchor",
                    "--root",
                    str(code),
                    "--query",
                    "refresh credentials",
                    "--expand-callers",
                    "--task",
                    CODE_TASKS["credentials_and_caller"],
                    "--analysis",
                    str(specs["code"]),
                    *common,
                ]
            ),
            lambda packet: check_selection(
                packet, ["persist_token", "renew_session", "refresh_credentials"], symbols=True
            ),
        )
        add(
            "python_cli_triage_8",
            python_runner(
                [
                    "triage",
                    "--input",
                    "-",
                    "--task",
                    TASK,
                    "--analysis",
                    str(specs["query"]),
                    *common,
                ],
                json.dumps(events),
            ),
            lambda packet: check_selection(packet, triage_expected),
        )
        add(
            "python_cli_diff_6",
            python_runner(
                [
                    "diff-review",
                    "--root",
                    str(diff_root),
                    "--unstaged",
                    "--task",
                    DIFF_TASK,
                    "--analysis",
                    str(specs["diff"]),
                    *common,
                ]
            ),
            lambda packet: check_selection(packet, diff_expected),
        )

        npm_root = base / "npm"
        installed = subprocess.run(
            [
                "npm",
                "install",
                "--prefix",
                str(npm_root),
                "--ignore-scripts",
                "--no-audit",
                "--no-fund",
                NPM_PACKAGE,
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=180,
        )
        package = npm_root / "node_modules/@apixly/jev-filter"
        if installed.returncode != 0:
            cases.append(
                {
                    "name": "fresh_published_npm_install",
                    "passed": False,
                    "error": "npm_install_failed",
                    "model_usage": usage_snapshot({}),
                }
            )
        else:
            metadata = json.loads((package / "package.json").read_text())
            result["installed_npm_version"] = metadata["version"]
            launcher = ["node", str(package / "npm/bin/jev-filter.cjs")]
            doctor, _, _ = execute([*launcher, "doctor"], cwd=base, env=env)
            result["installed_native_version"] = doctor.get("version")
            result["fresh_install_verified"] = (
                metadata["version"] == doctor.get("version") == "0.4.0" and doctor.get("ok") is True
            )

            def js_runner(method, options, **arguments):
                payload = {
                    "module": str(package),
                    "cwd": str(base),
                    "method": method,
                    "options": options,
                    **arguments,
                }
                payload_path = write_json(base / f"js-{method}.json", payload)

                def run():
                    response, _, size = execute(
                        ["node", "-e", JS_SCRIPT, str(payload_path)], cwd=base, env=env
                    )
                    if response.get("failed"):
                        raise RuntimeError("adapter_failed")
                    return response["packet"], response["exitCode"], size

                return run

            add(
                "published_js_query_32",
                js_runner(
                    "query",
                    {"task": TASK, "analysis": {**SPEC, "model": MODEL}, "budgetChars": 12000},
                    records=records,
                ),
                lambda packet: check_selection(packet, query_expected),
            )
            add(
                "published_js_code_recall",
                js_runner(
                    "codeSearch",
                    {
                        "task": CODE_TASKS["credentials_and_caller"],
                        "root": str(code),
                        "query": "refresh credentials",
                        "expandCallers": True,
                        "analysis": code_spec(),
                        "budgetChars": 12000,
                    },
                    pattern="token_anchor",
                ),
                lambda packet: check_selection(
                    packet, ["persist_token", "renew_session", "refresh_credentials"], symbols=True
                ),
            )
            add(
                "published_js_triage_8",
                js_runner(
                    "triage",
                    {"task": TASK, "analysis": {**SPEC, "model": MODEL}, "budgetChars": 12000},
                    events=events,
                ),
                lambda packet: check_selection(packet, triage_expected),
            )
            add(
                "published_js_diff_6",
                js_runner(
                    "diffReview",
                    {
                        "task": DIFF_TASK,
                        "root": str(diff_root),
                        "unstaged": True,
                        "analysis": diff_spec(),
                        "budgetChars": 12000,
                    },
                ),
                lambda packet: check_selection(packet, diff_expected),
            )
            try:
                asyncio.run(
                    run_official_mcp(
                        launcher, base, env, add, records, query_expected, events, triage_expected
                    )
                )
            except Exception as error:
                cases.append(
                    {
                        "name": "published_native_official_mcp_connection",
                        "passed": False,
                        "error_type": type(error).__name__,
                        "model_usage": usage_snapshot({}),
                    }
                )

        html_rows = "".join(
            "<tr>"
            + "".join(
                f"<td>{html.escape(str(value))}</td>"
                for value in (sku, category, stock, f"${price}", charging)
            )
            + "</tr>"
            for sku, category, stock, price, charging in OFFERS
        )
        document = (
            "<!doctype html><title>Synthetic offers</title><div id='offers'><table><thead><tr><th>SKU</th><th>Category</th><th>Stock</th><th>Price</th><th>Charging</th></tr></thead><tbody>"
            + html_rows
            + "</tbody></table></div>"
        ).encode()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(document)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def verify_extract(packet):
            raw = json.loads(Path(packet["archive"]).read_text())
            by_id = {row["id"]: row["text"] for row in raw["records"]}
            skus, prices = [], {}
            for rid in packet["selected_ids"]:
                text = by_id[rid]
                sku = re.search(r"SKU: (L\d+)", text).group(1)
                prices[sku] = int(re.search(r"Price: \$(\d+)", text).group(1))
                skus.append(sku)
            final = extract_price_filter(skus, prices)
            return {
                "passed": packet.get("complete") is True
                and set(skus) == {"L1", "L3", "L4", "L7"}
                and final == ["L1", "L4", "L7"],
                "semantic_selected_skus": sorted(skus),
                "deterministic_price_under_35_skus": final,
                "price_comparison_owner": "program; exact numeric data parsed from collected source rows",
            }

        try:
            add(
                "python_cli_local_table_extract",
                python_runner(
                    [
                        "extract",
                        "--url",
                        f"http://127.0.0.1:{server.server_port}/table.html",
                        "--scope",
                        "#offers",
                        "--task",
                        "Select in-stock lamps supporting USB-C charging. Price will be filtered separately in code.",
                        "--analysis",
                        str(specs["extract"]),
                        *common,
                    ]
                ),
                verify_extract,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        survey_records, labels, counts = survey_fixture()
        records_path = write_json(base / "survey-records.json", survey_records)
        labels_path = base / "survey-labels.jsonl"
        labels_path.write_text(
            "\n".join(json.dumps(row) for row in labels) + "\n", encoding="utf-8"
        )
        spec_path = write_json(base / "survey-spec.json", SURVEY_SPEC)
        add(
            "python_cli_survey_64",
            python_runner(
                [
                    "survey",
                    "--input",
                    str(records_path),
                    "--spec",
                    str(spec_path),
                    "--labels",
                    str(labels_path),
                    "--workers",
                    "4",
                    "--budget-chars",
                    "12000",
                ]
            ),
            lambda packet: {
                "passed": packet.get("complete") is True
                and packet.get("evaluated") == 64
                and packet["questions"]["topic"]["counts"] == counts
                and packet["calibration"]["topic"]["accuracy"] == 1.0,
                "expected_topic_counts": counts,
                "actual_topic_counts": packet["questions"]["topic"]["counts"],
                "labels_accuracy": packet["calibration"]["topic"]["accuracy"],
            },
        )
    result["passed"] = (
        all(case["passed"] for case in cases) and result.get("fresh_install_verified") is True
    )
    result["actual_known_usage"] = {
        key: sum(case.get("model_usage", {}).get("known_usage", {}).get(key) or 0 for case in cases)
        for key in ("input_tokens", "output_tokens")
    }
    result["usage_complete"] = all(
        case.get("model_usage", {}).get("usage_complete") is True for case in cases
    )
    result["logical_requests"] = sum(
        case.get("model_usage", {}).get("requests") or 0 for case in cases
    )
    return result


async def run_official_mcp(
    launcher, workspace, env, add, records, query_expected, events, triage_expected
):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async with stdio_client(
        StdioServerParameters(
            command=launcher[0], args=[*launcher[1:], "mcp", "--root", str(workspace)], env=env
        )
    ) as (read, write):
        async with ClientSession(read, write) as session:
            initialized = await session.initialize()
            tools = await session.list_tools()
            for name, tool, arguments, expected, symbols in (
                (
                    "published_native_official_mcp_filter",
                    "filter_records",
                    {
                        "task": TASK,
                        "records": records,
                        "analysis": {**SPEC, "model": MODEL},
                        "budget_chars": 12000,
                    },
                    query_expected,
                    False,
                ),
                (
                    "published_native_official_mcp_search",
                    "search_code",
                    {
                        "task": CODE_TASKS["credentials_and_caller"],
                        "root": "code",
                        "pattern": "token_anchor",
                        "query": "refresh credentials",
                        "expand_callers": True,
                        "analysis": code_spec(),
                        "budget_chars": 12000,
                    },
                    ["persist_token", "renew_session", "refresh_credentials"],
                    True,
                ),
                (
                    "published_native_official_mcp_triage",
                    "triage_events",
                    {
                        "task": TASK,
                        "events": events,
                        "analysis": {**SPEC, "model": MODEL},
                        "budget_chars": 12000,
                    },
                    triage_expected,
                    False,
                ),
            ):
                started = time.perf_counter()
                packet = {}
                try:
                    response = await session.call_tool(tool, arguments)
                    packet = response.structuredContent or {}
                    verified = check_selection(packet, expected, symbols=symbols)
                    if tool == "filter_records" and packet.get("archive"):
                        evidence = await session.call_tool(
                            "read_evidence",
                            {"archive": packet["archive"], "id": "r000", "budget_chars": 12000},
                        )
                        observed = evidence.structuredContent or {}
                        verified["evidence_roundtrip"] = (
                            observed.get("text") == records[0]["text"]
                            and observed.get("sha256")
                            == hashlib.sha256(records[0]["text"].encode()).hexdigest()
                            and observed.get("display_truncated") is False
                        )
                        verified["passed"] &= verified["evidence_roundtrip"]
                except Exception as error:
                    verified = {
                        "passed": False,
                        "error_type": type(error).__name__,
                        "error": "mcp_call_or_verification_failed",
                    }
                outcome = add(
                    name,
                    lambda packet=packet: (packet, None, len(json.dumps(packet).encode())),
                    lambda p, verified=verified: verified,
                )
                outcome.update(
                    whole_operation_ms=round((time.perf_counter() - started) * 1000, 3),
                    protocol=initialized.protocolVersion,
                    listed_tools=len(tools.tools),
                )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--cli")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        parser.error("output exists; preserve earlier evidence")
    result = benchmark(live=args.live, cli=args.cli)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                key: result.get(key)
                for key in (
                    "kind",
                    "passed",
                    "logical_requests",
                    "actual_known_usage",
                    "usage_complete",
                )
            }
        )
    )
    return 0 if not args.live or result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
