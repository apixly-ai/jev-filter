"""Read-only MCP scope, evidence and wire contracts; no API calls."""

import io
import json

import pytest

from jev_context.mcp import Server, serve


def request(method, params=None, rid=1):
    return {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}


def test_handshake_tools_and_unknown_methods(tmp_path):
    server = Server(tmp_path)
    assert server.handle(request("tools/list"))["error"]["code"] == -32002
    initialized = server.handle(
        request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
    )
    assert initialized["result"]["protocolVersion"] == "2025-06-18"
    tools = server.handle(request("tools/list"))["result"]["tools"]
    assert {t["name"] for t in tools} == {
        "filter_records",
        "search_code",
        "triage_events",
        "read_evidence",
    }
    assert all(t["annotations"]["readOnlyHint"] for t in tools)
    assert server.handle(request("exec"))["error"]["code"] == -32601
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_filter_missing_context_preserves_review_and_evidence(tmp_path):
    server = Server(tmp_path)
    server.handle(request("initialize"))
    result = server.handle(
        request(
            "tools/call",
            {
                "name": "filter_records",
                "arguments": {
                    "task": "Find current failure",
                    "records": [{"id": "x", "text": "Synthetic failure"}],
                    "analysis": {"required_context": ["deployment"]},
                },
            },
        )
    )["result"]
    packet = result["structuredContent"]
    assert packet["review_ids"] == ["x"] and packet["complete"] is False
    assert packet["telemetry"]["usage"]["input_tokens"] == 0
    evidence = server.handle(
        request(
            "tools/call",
            {"name": "read_evidence", "arguments": {"archive": packet["archive"], "id": "x"}},
        )
    )["result"]["structuredContent"]
    assert evidence["text"] == "Synthetic failure"
    assert evidence["sha256"]


def test_scope_and_unregistered_archive_are_refused(tmp_path):
    root = tmp_path / "scope"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)
    server = Server(root)
    server.handle(request("initialize"))
    for arguments in ({"root": "../outside"}, {"root": "escape"}):
        reply = server.handle(
            request(
                "tools/call",
                {
                    "name": "search_code",
                    "arguments": {"task": "Find code", "pattern": ".", **arguments},
                },
            )
        )["result"]
        assert reply["isError"] is True
        assert "outside" not in reply["content"][0]["text"]
    reply = server.handle(
        request(
            "tools/call",
            {"name": "read_evidence", "arguments": {"archive": str(outside), "id": "x"}},
        )
    )["result"]
    assert reply["isError"] is True


def test_archive_changes_and_payload_budgets_are_refused(tmp_path):
    server = Server(tmp_path)
    server.handle(request("initialize"))
    reply = server.handle(
        request("tools/call", {"name": "filter_records", "arguments": {"task": "x", "records": []}})
    )["result"]
    packet = reply["structuredContent"]
    from pathlib import Path

    Path(packet["archive"]).write_text('{"records":[]}')
    result = server.handle(
        request(
            "tools/call",
            {"name": "read_evidence", "arguments": {"archive": packet["archive"], "id": "x"}},
        )
    )["result"]
    assert result["isError"] is True
    result = server.handle(
        request(
            "tools/call",
            {
                "name": "filter_records",
                "arguments": {"task": "x", "records": [{"text": "x" * 1_100_000}]},
            },
        )
    )["result"]
    assert result["isError"] is True


def test_stdio_returns_only_jsonrpc_and_survives_bad_json(tmp_path):
    source = io.StringIO(
        "not json\n"
        + json.dumps(request("initialize"))
        + "\n"
        + json.dumps(request("ping", rid=2))
        + "\n"
    )
    output = io.StringIO()
    serve(Server(tmp_path), source, output)
    replies = [json.loads(line) for line in output.getvalue().splitlines()]
    assert replies[0]["error"]["code"] == -32700
    assert replies[1]["result"]["serverInfo"]["name"] == "jev-filter"
    assert replies[2] == {"jsonrpc": "2.0", "id": 2, "result": {}}


def test_search_context_admission_precedes_code_collection(tmp_path, monkeypatch):
    import jev_context.tools

    def forbidden(*args, **kwargs):
        raise AssertionError("required context must be admitted before code collection")

    monkeypatch.setattr(jev_context.tools, "collect_code", forbidden)
    server = Server(tmp_path)
    packet = server.call(
        "search_code",
        {
            "task": "Find current handler",
            "pattern": "handler",
            "analysis": {"required_context": ["deployment"]},
        },
    )
    assert packet["status"] == "NEEDS_CONTEXT"
    assert packet["collection_skipped"] is True
    assert packet["telemetry"]["requests"] == 0


@pytest.mark.parametrize(
    "message", [[], {"method": "ping"}, {"jsonrpc": "2.0", "id": {}, "method": "ping"}]
)
def test_invalid_rpc_has_structured_error(tmp_path, message):
    assert Server(tmp_path).handle(message)["error"]["code"] == -32600


def test_search_rechecks_sources_after_judgment(tmp_path, monkeypatch):
    from jev_context import tools

    source = tmp_path / "handler.py"
    source.write_text("def handler():\n    return 'needle'\n")

    def analyzed(records, *_args, **_kwargs):
        source.write_text("def handler():\n    return 'changed'\n")
        return {
            "ok": True,
            "selected_ids": [records[0]["id"]],
            "review_ids": [],
            "complete": True,
            "excerpts": [{"source_id": records[0]["id"]}],
        }

    monkeypatch.setattr(tools, "analyze_records", analyzed)
    server = Server(tmp_path)
    packet = server.call("search_code", {"task": "Find handler", "pattern": "needle"})
    assert packet["selected_ids"] == []
    assert packet["review_ids"] and packet["complete"] is False
    assert packet["changed_sources"] == packet["review_ids"]


def test_filter_metadata_stays_in_archive_not_compact_packet(tmp_path):
    server = Server(tmp_path)
    packet = server.call(
        "filter_records",
        {
            "task": "Find failure",
            "records": [
                {"id": "x", "text": "Synthetic failure", "extra": "large metadata " * 1000}
            ],
            "analysis": {"required_context": ["missing"]},
        },
    )
    assert "large metadata" not in json.dumps(packet)


def test_large_identity_and_nonfinite_input_fail_before_inference(tmp_path):
    server = Server(tmp_path)
    server.handle(request("initialize"))
    for record in (
        {"id": "x" * 300, "text": "fixture"},
        {"id": "x", "text": "fixture", "score": float("nan")},
    ):
        result = server.handle(
            request(
                "tools/call",
                {
                    "name": "filter_records",
                    "arguments": {
                        "task": "x",
                        "records": [record],
                        "analysis": {"required_context": ["missing"]},
                    },
                },
            )
        )["result"]
        assert result["isError"] is True
