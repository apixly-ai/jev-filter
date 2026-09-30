"""Standard-library WebSocket/CDP client: framing, handshake and loopback-only policy."""

import base64
import hashlib
import json
import socket
import struct
import threading

import pytest

from jev_context.act import cdp

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _read_frame(conn):
    head = conn.recv(2)
    fin, opcode = head[0] & 0x80, head[0] & 0x0F
    masked, size = head[1] & 0x80, head[1] & 0x7F
    if size == 126:
        size = struct.unpack(">H", conn.recv(2))[0]
    elif size == 127:
        size = struct.unpack(">Q", conn.recv(8))[0]
    key = conn.recv(4) if masked else b""
    data = b""
    while len(data) < size:
        data += conn.recv(size - len(data))
    if masked:
        data = bytes(b ^ key[i % 4] for i, b in enumerate(data))
    return bool(fin), opcode, bool(masked), data


def _frame(opcode, data, fin=True):
    head = bytes([(0x80 if fin else 0) | opcode])
    if len(data) < 126:
        head += bytes([len(data)])
    elif len(data) < 65536:
        head += bytes([126]) + struct.pack(">H", len(data))
    else:
        head += bytes([127]) + struct.pack(">Q", len(data))
    return head + data


class FakeDevTools:
    """A one-connection server speaking just enough RFC 6455 to test the client."""

    def __init__(self, handler, accept_override=None):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.handler = handler
        self.accept_override = accept_override
        self.seen = []
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        conn, _ = self.sock.accept()
        request = b""
        while b"\r\n\r\n" not in request:
            request += conn.recv(4096)
        headers = {}
        for line in request.decode().split("\r\n")[1:]:
            if ": " in line:
                k, v = line.split(": ", 1)
                headers[k.lower()] = v
        accept = (
            self.accept_override
            or base64.b64encode(
                hashlib.sha1((headers["sec-websocket-key"] + GUID).encode()).digest()
            ).decode()
        )
        conn.sendall(
            (
                "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                f"Connection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n"
            ).encode()
        )
        try:
            self.handler(self, conn)
        finally:
            conn.close()
            self.sock.close()


def test_masked_text_roundtrip_with_fragmentation_and_ping():
    def handler(server, conn):
        fin, opcode, masked, data = _read_frame(conn)
        server.seen.append((fin, opcode, masked, data))
        message = json.loads(data)
        reply = json.dumps({"id": message["id"], "result": {"echo": message["params"]}}).encode()
        conn.sendall(_frame(0x9, b"hi"))  # ping must be answered and not surface
        conn.sendall(_frame(0x1, reply[:5], fin=False) + _frame(0x0, reply[5:]))
        server.seen.append(_read_frame(conn))  # pong

    server = FakeDevTools(handler)
    with cdp.Connection(f"ws://127.0.0.1:{server.port}/devtools/browser/x", timeout=5) as conn:
        assert conn.call("Test.echo", {"value": "中文" * 3}) == {"echo": {"value": "中文" * 3}}
    server.thread.join(5)
    fin, opcode, masked, _ = server.seen[0]
    assert fin and opcode == 0x1 and masked
    assert server.seen[1][1] == 0xA and server.seen[1][3] == b"hi"


def test_large_payload_uses_extended_length():
    def handler(server, conn):
        fin, opcode, masked, data = _read_frame(conn)
        message = json.loads(data)
        big = json.dumps({"id": message["id"], "result": {"data": "x" * 70000}}).encode()
        conn.sendall(_frame(0x1, big))

    server = FakeDevTools(handler)
    with cdp.Connection(f"ws://127.0.0.1:{server.port}/x", timeout=5) as conn:
        assert len(conn.call("Big.payload", {"blob": "y" * 70000})["data"]) == 70000


def test_events_are_buffered_and_errors_raise():
    def handler(server, conn):
        _, _, _, data = _read_frame(conn)
        mid = json.loads(data)["id"]
        conn.sendall(
            _frame(0x1, json.dumps({"method": "Page.loadEventFired", "params": {}}).encode())
        )
        conn.sendall(
            _frame(
                0x1,
                json.dumps({"id": mid, "error": {"code": -32000, "message": "boom"}}).encode(),
            )
        )

    server = FakeDevTools(handler)
    with cdp.Connection(f"ws://127.0.0.1:{server.port}/x", timeout=5) as conn:
        with pytest.raises(cdp.CDPError, match="boom"):
            conn.call("Page.fail")
        assert [e["method"] for e in conn.drain_events()] == ["Page.loadEventFired"]


def test_bad_handshake_is_rejected():
    server = FakeDevTools(lambda s, c: None, accept_override="wrong")
    with pytest.raises(cdp.CDPError, match="handshake"):
        cdp.Connection(f"ws://127.0.0.1:{server.port}/x", timeout=5)


@pytest.mark.parametrize(
    "url",
    [
        "ws://10.0.0.5:9222/x",
        "ws://example.com:9222/x",
        "wss://127.0.0.1:9222/x",
        "http://127.0.0.1/",
    ],
)
def test_only_loopback_plain_websocket_is_allowed(url):
    with pytest.raises(cdp.CDPError, match="loopback"):
        cdp.Connection(url, timeout=1)


def test_find_chromium_prefers_explicit_path(tmp_path):
    exe = tmp_path / "chrome.exe"
    exe.write_bytes(b"")
    assert cdp.find_chromium(str(exe)) == str(exe)
    with pytest.raises(cdp.CDPError, match="not found"):
        cdp.find_chromium(str(tmp_path / "missing.exe"))


def test_event_handler_can_issue_nested_call_while_outer_call_waits():
    """A blocking dialog event arrives before the evaluate reply; handling it must not drop it."""

    def handler(server, conn):
        _, _, _, data = _read_frame(conn)
        outer = json.loads(data)["id"]
        conn.sendall(
            _frame(
                0x1,
                json.dumps(
                    {"method": "Page.javascriptDialogOpening", "params": {"type": "confirm"}}
                ).encode(),
            )
        )
        _, _, _, data = _read_frame(conn)  # nested dismiss call from the handler
        nested = json.loads(data)
        server.seen.append(nested["method"])
        # Reply to the outer call first, then to the nested call.
        conn.sendall(_frame(0x1, json.dumps({"id": outer, "result": {"v": 1}}).encode()))
        conn.sendall(_frame(0x1, json.dumps({"id": nested["id"], "result": {}}).encode()))

    server = FakeDevTools(handler)
    with cdp.Connection(f"ws://127.0.0.1:{server.port}/x", timeout=5) as conn:
        conn.on(
            "Page.javascriptDialogOpening",
            lambda event: conn.call("Page.handleJavaScriptDialog", {"accept": False}),
        )
        assert conn.call("Runtime.evaluate") == {"v": 1}
    server.thread.join(5)
    assert server.seen == ["Page.handleJavaScriptDialog"]
