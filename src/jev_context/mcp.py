"""Small read-only MCP stdio adapter over the existing evidence core.

Supports the connection-scoped 2024-11-05 through 2025-11-25 protocol revisions.
No commands, actions, selectors or arbitrary file reads are exposed as tools.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

MAX_BYTES = 1_000_000
VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")


def schema(properties, required):
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


TEXT = {"type": "string", "minLength": 1}
COMMON = {
    "task": TEXT,
    "analysis": {"type": "object"},
    "budget_chars": {"type": "integer", "minimum": 1, "maximum": 12000},
}
TOOLS = [
    {
        "name": "filter_records",
        "description": "Filter supplied records with explicit task/context. Returns selected and unresolved IDs plus evidence receipts.",
        "inputSchema": schema(
            {
                **COMMON,
                "records": {
                    "type": "array",
                    "maxItems": 500,
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "minLength": 1, "maxLength": 256},
                            "text": {"type": "string"},
                        },
                        "required": ["text"],
                    },
                },
            },
            ["task", "records"],
        ),
    },
    {
        "name": "search_code",
        "description": "Collect bounded code candidates inside the configured workspace and judge relevance. Exact regex scope is always reported.",
        "inputSchema": schema(
            {
                **COMMON,
                "pattern": TEXT,
                "root": TEXT,
                "query": TEXT,
                "expand_callers": {"type": "boolean"},
                "max_files": {"type": "integer", "minimum": 1, "maximum": 10000},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
            },
            ["task", "pattern"],
        ),
    },
    {
        "name": "triage_events",
        "description": "Redact and correlate supplied JSON events, then select relevant incidents. No log file or shell access.",
        "inputSchema": schema(
            {
                **COMMON,
                "events": {"type": "array", "maxItems": 500, "items": {"type": "object"}},
                "group_by": TEXT,
            },
            ["task", "events"],
        ),
    },
    {
        "name": "read_evidence",
        "description": "Read one bounded record from an unchanged receipt produced in this server session. A receipt never grants action authority.",
        "inputSchema": schema(
            {
                "archive": TEXT,
                "id": TEXT,
                "budget_chars": {"type": "integer", "minimum": 1, "maximum": 12000},
            },
            ["archive", "id"],
        ),
    },
]
for definition in TOOLS:
    definition["annotations"] = {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": definition["name"] != "read_evidence",
    }


class Server:
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("workspace_directory_required")
        self.initialized = False
        self.archives = {}

    def scoped(self, value):
        target = (self.root / value).resolve(strict=True)
        try:
            target.relative_to(self.root)
        except ValueError:
            raise ValueError("workspace_scope_refused") from None
        return target

    def retain(self, packet):
        for name in ("archive", "receipt"):
            if packet.get(name):
                path = Path(packet[name])
                self.archives[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        return packet

    @staticmethod
    def validate_arguments(tool, arguments):
        if not isinstance(arguments, dict):
            raise ValueError("arguments_object_required")
        expected = tool["inputSchema"]
        if set(arguments) - set(expected["properties"]) or set(expected["required"]) - set(
            arguments
        ):
            raise ValueError("invalid_arguments")
        for key, value in arguments.items():
            rule = expected["properties"][key]
            kind = rule["type"]
            valid = (
                (kind == "string" and isinstance(value, str) and bool(value.strip()))
                or (kind == "object" and isinstance(value, dict))
                or (kind == "array" and isinstance(value, list))
                or (
                    kind == "integer"
                    and type(value) is int
                    and rule["minimum"] <= value <= rule["maximum"]
                )
                or (kind == "boolean" and type(value) is bool)
            )
            if not valid:
                raise ValueError("invalid_argument_type")
            if kind == "array" and (
                len(value) > rule["maxItems"] or any(not isinstance(row, dict) for row in value)
            ):
                raise ValueError("record_budget_exceeded")
        if len(json.dumps(arguments, ensure_ascii=False, allow_nan=False).encode()) > MAX_BYTES:
            raise ValueError("request_budget_exceeded")
        for record in arguments.get("records", []):
            if "id" in record and (
                not isinstance(record["id"], str) or not 1 <= len(record["id"]) <= 256
            ):
                raise ValueError("record_identity_budget_exceeded")

    def call(self, name, arguments):
        from . import analysis
        from .tools import analyze_records, collect_code, collect_logs, guard_code_sources

        definition = next((tool for tool in TOOLS if tool["name"] == name), None)
        if definition is None:
            raise ValueError("unknown_tool")
        self.validate_arguments(definition, arguments)
        budget = arguments.get("budget_chars", 4000)
        if name == "search_code":
            # Required facts are admitted before starting any collector subprocess or file read.
            spec = analysis.validate(arguments.get("analysis"))
            admission = analysis.context_admission(spec)
            if admission:
                return admission
        if name == "read_evidence":
            key = arguments["archive"]
            if key not in self.archives:
                raise ValueError("unregistered_archive")
            path = Path(key)
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != self.archives[key]:
                raise ValueError("archive_changed")
            records = json.loads(raw)["records"]
            record = next((r for r in records if r["id"] == arguments["id"]), None)
            if record is None:
                raise ValueError("unknown_record")
            text = record["text"]
            return {
                "id": record["id"],
                "text": text[:budget],
                "sha256": hashlib.sha256(text.encode()).hexdigest(),
                "display_truncated": len(text) > budget,
            }
        if name == "filter_records":
            records = arguments["records"]
            collection = {"ok": True, "scope": "caller-supplied records"}
        elif name == "search_code":
            root = self.scoped(arguments.get("root", "."))
            records, collection = collect_code(
                root,
                arguments["pattern"],
                arguments.get("limit", 100),
                query=arguments.get("query"),
                expand_callers=arguments.get("expand_callers", False),
                max_files=arguments.get("max_files", 2000),
            )
        else:
            records, collection = collect_logs(
                "\n".join(json.dumps(event) for event in arguments["events"]),
                arguments.get("group_by", "request_id"),
            )
        packet = analyze_records(
            records, arguments["task"], arguments.get("analysis"), collection, budget=budget
        )
        if name == "search_code":
            from .cli import save_archive

            packet = guard_code_sources(packet, records)
            packet["receipt"] = save_archive({"records": records, "result": packet})
        self.retain(packet)
        # MCP keeps the stable evidence packet projection. Full record-specific
        # metadata and custom display projections remain in the private receipt.
        allowed = {
            "source_id",
            "text",
            "status",
            "answers",
            "start",
            "end",
            "display_truncated",
            "decision",
        }
        source_fields = {
            "path",
            "symbol",
            "line",
            "end_line",
            "source_sha256",
            "boundary",
            "fetch_error",
        }
        excerpts = []
        for row in packet.get("excerpts", []):
            compact = {k: v for k, v in row.items() if k in allowed}
            if isinstance(row.get("source"), dict):
                compact["source"] = {
                    k: v
                    for k, v in row["source"].items()
                    if k in source_fields
                    and not isinstance(v, (dict, list))
                    and len(str(v)) <= 1024
                }
            if compact:
                excerpts.append(compact)
        packet["excerpts"] = excerpts
        while (
            len(json.dumps(packet, ensure_ascii=False).encode()) > MAX_BYTES and packet["excerpts"]
        ):
            packet["excerpts"].pop()
            packet["display_incomplete"] = True
        if len(json.dumps(packet, ensure_ascii=False, allow_nan=False).encode()) > MAX_BYTES:
            return {
                "ok": False,
                "complete": False,
                "error": "result_budget_exceeded",
                "archive": packet.get("archive"),
                "receipt": packet.get("receipt"),
            }
        return packet

    def handle(self, message):
        valid = (
            isinstance(message, dict)
            and message.get("jsonrpc") == "2.0"
            and isinstance(message.get("method"), str)
        )
        rid = message.get("id") if isinstance(message, dict) else None
        if not valid or ("id" in message and type(rid) not in (int, str)):
            return rpc_error(None, -32600, "Invalid Request")
        method = message["method"]
        if "id" not in message:
            return None
        params = message.get("params", {})
        if not isinstance(params, dict):
            return rpc_error(rid, -32602, "Invalid params")
        if method == "initialize":
            from . import __version__

            version = params.get("protocolVersion")
            self.initialized = True
            result = {
                "protocolVersion": version if version in VERSIONS else VERSIONS[0],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "jev-filter", "version": __version__},
                "instructions": "Read-only semantic decisions. Configure a workspace scope; decisions never authorize external actions.",
            }
        elif method == "ping":
            result = {}
        elif not self.initialized:
            return rpc_error(rid, -32002, "Initialize first")
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            try:
                packet = self.call(params.get("name"), params.get("arguments", {}))
                result = {
                    "content": [{"type": "text", "text": json.dumps(packet, ensure_ascii=False)}],
                    "structuredContent": packet,
                    "isError": packet.get("ok") is False,
                }
            except (ValueError, OSError, KeyError, TypeError) as error:
                # Do not echo paths, supplied content, provider bodies or credentials.
                code = (
                    str(error)
                    if str(error)
                    in {
                        "workspace_scope_refused",
                        "unregistered_archive",
                        "archive_changed",
                        "unknown_record",
                        "unknown_tool",
                        "record_budget_exceeded",
                        "request_budget_exceeded",
                        "record_identity_budget_exceeded",
                        "invalid_arguments",
                        "invalid_argument_type",
                        "arguments_object_required",
                    }
                    else type(error).__name__
                )
                result = {
                    "content": [{"type": "text", "text": json.dumps({"ok": False, "error": code})}],
                    "isError": True,
                }
        else:
            return rpc_error(rid, -32601, "Method not found")
        return {"jsonrpc": "2.0", "id": rid, "result": result}


def rpc_error(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def serve(server, source, output):
    while True:
        line = source.readline(MAX_BYTES + 1)
        if not line:
            return
        if len(line.encode()) > MAX_BYTES:
            while line and not line.endswith("\n"):
                line = source.readline(MAX_BYTES + 1)
            result = rpc_error(None, -32600, "Request budget exceeded")
        else:
            try:

                def reject_constant(_value):
                    raise ValueError("Nonfinite JSON number")

                result = server.handle(json.loads(line, parse_constant=reject_constant))
            except (ValueError, UnicodeError):
                result = rpc_error(None, -32700, "Parse error")
        if result is not None:
            output.write(json.dumps(result, ensure_ascii=False) + "\n")
            output.flush()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", default=".", help="Explicit workspace boundary for code collection"
    )
    args = parser.parse_args(argv)
    serve(Server(args.root), sys.stdin, sys.stdout)
    return 0
