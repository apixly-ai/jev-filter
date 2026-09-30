"""Chrome DevTools Protocol over a standard-library WebSocket client.

Only loopback ``ws://`` endpoints are accepted: DevTools grants full control of the browser
profile, so a remote or TLS endpoint is never a legitimate target for this tool. There is no
third-party dependency, which keeps the frozen npm distribution unchanged.
"""

import base64
import hashlib
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
MAX_MESSAGE = 64 * 1024 * 1024


class CDPError(RuntimeError):
    """A DevTools transport, handshake or protocol failure."""


def _mask(data: bytes, key: bytes) -> bytes:
    if not data:
        return data
    repeated = (key * (len(data) // 4 + 1))[: len(data)]
    return (int.from_bytes(data, "big") ^ int.from_bytes(repeated, "big")).to_bytes(
        len(data), "big"
    )


def _check_loopback(url: str) -> urllib.parse.SplitResult:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "ws" or (parts.hostname or "") not in LOOPBACK:
        raise CDPError("DevTools endpoint must be a loopback ws:// URL")
    return parts


class Connection:
    """One DevTools WebSocket. Calls are synchronous; events are buffered for later draining."""

    def __init__(self, url: str, timeout: float = 30):
        parts = _check_loopback(url)
        self.timeout = timeout
        self.next_id = 0
        self.events: list[dict] = []
        self.replies: dict[int, dict] = {}
        self.handlers: dict[str, object] = {}
        self.closed = False
        host = parts.hostname
        port = parts.port or 80
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        try:
            self.sock = socket.create_connection((host, port), timeout=timeout)
        except OSError as error:
            raise CDPError(f"cannot connect to DevTools: {type(error).__name__}") from None
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.buffer = b""
        try:
            self.sock.sendall(request.encode())
            while b"\r\n\r\n" not in self.buffer:
                chunk = self.sock.recv(4096)
                if not chunk:
                    raise CDPError("handshake closed")
                self.buffer += chunk
                if len(self.buffer) > 65536:
                    raise CDPError("handshake too large")
        except OSError:
            self.sock.close()
            raise CDPError("handshake failed") from None
        head, self.buffer = self.buffer.split(b"\r\n\r\n", 1)
        lines = head.decode("latin-1").split("\r\n")
        headers = {}
        for line in lines[1:]:
            name, _, value = line.partition(":")
            headers[name.strip().lower()] = value.strip()
        expected = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
        if " 101 " not in lines[0] + " " or headers.get("sec-websocket-accept") != expected:
            self.sock.close()
            raise CDPError("WebSocket handshake rejected")

    def _read(self, size: int) -> bytes:
        while len(self.buffer) < size:
            try:
                chunk = self.sock.recv(max(65536, size - len(self.buffer)))
            except socket.timeout:
                raise CDPError("DevTools read timed out") from None
            except OSError:
                raise CDPError("DevTools connection failed") from None
            if not chunk:
                raise CDPError("DevTools connection closed")
            self.buffer += chunk
        data, self.buffer = self.buffer[:size], self.buffer[size:]
        return data

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        head = bytes([0x80 | opcode])
        size = len(payload)
        if size < 126:
            head += bytes([0x80 | size])
        elif size < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", size)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", size)
        key = os.urandom(4)
        try:
            self.sock.sendall(head + key + _mask(payload, key))
        except OSError:
            raise CDPError("DevTools send failed") from None

    def _message(self) -> dict:
        parts = []
        total = 0
        while True:
            b0, b1 = self._read(2)
            fin, opcode = b0 & 0x80, b0 & 0x0F
            size = b1 & 0x7F
            if size == 126:
                size = struct.unpack(">H", self._read(2))[0]
            elif size == 127:
                size = struct.unpack(">Q", self._read(8))[0]
            key = self._read(4) if b1 & 0x80 else b""
            if size > MAX_MESSAGE:
                raise CDPError("DevTools message too large")
            payload = self._read(size)
            if key:
                payload = _mask(payload, key)
            if opcode == 0x9:
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x8:
                self.closed = True
                raise CDPError("DevTools closed the connection")
            if opcode in (0x1, 0x2, 0x0):
                parts.append(payload)
                total += len(payload)
                if total > MAX_MESSAGE:
                    raise CDPError("DevTools message too large")
                if fin:
                    try:
                        return json.loads(b"".join(parts))
                    except ValueError:
                        raise CDPError("DevTools sent invalid JSON") from None
                continue
            raise CDPError("unexpected WebSocket opcode")

    def on(self, method: str, handler) -> None:
        """Run ``handler(event)`` synchronously when an event arrives, even mid-call.

        Handlers may issue nested calls (e.g. dismiss a JavaScript dialog that blocks an
        in-flight ``Runtime.evaluate``); replies for other calls are kept, never dropped.
        """
        self.handlers[method] = handler

    def _pump(self) -> None:
        message = self._message()
        if "id" in message:
            self.replies[message["id"]] = message
            return
        if "method" in message:
            self.events.append(message)
            if len(self.events) > 2000:
                del self.events[:1000]
            handler = self.handlers.get(message["method"])
            if handler:
                handler(message)

    def call(
        self,
        method: str,
        params: dict | None = None,
        session_id: str | None = None,
        timeout: float | None = None,
    ) -> dict:
        if self.closed:
            raise CDPError("DevTools connection closed")
        self.next_id += 1
        mid = self.next_id
        message = {"id": mid, "method": method, "params": params or {}}
        if session_id:
            message["sessionId"] = session_id
        self._send_frame(0x1, json.dumps(message, ensure_ascii=False).encode())
        deadline = time.monotonic() + (timeout or self.timeout)
        while mid not in self.replies:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CDPError(f"{method} timed out")
            self.sock.settimeout(remaining)
            self._pump()
        reply = self.replies.pop(mid)
        if "error" in reply:
            raise CDPError(f"{method}: {reply['error'].get('message', 'error')}")
        return reply.get("result", {})

    def drain_events(self) -> list[dict]:
        events, self.events = self.events, []
        return events

    def close(self) -> None:
        if not self.closed:
            try:
                self._send_frame(0x8, b"")
            except CDPError:
                pass
        self.closed = True
        try:
            self.sock.close()
        except OSError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def browser_ws_url(port: int, timeout: float = 5) -> str:
    """Resolve the browser-level WebSocket from a loopback DevTools HTTP port."""
    if not 1 <= int(port) <= 65535:
        raise CDPError("invalid DevTools port")
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{int(port)}/json/version", timeout=timeout
        ) as r:
            url = json.load(r)["webSocketDebuggerUrl"]
    except (OSError, ValueError, KeyError):
        raise CDPError("DevTools endpoint unavailable") from None
    _check_loopback(url)
    return url


def _candidates() -> list[str]:
    if sys.platform == "win32":
        roots = [
            os.environ.get(k, "") for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")
        ]
        rel = [
            r"Google\Chrome\Application\chrome.exe",
            r"Microsoft\Edge\Application\msedge.exe",
            r"Chromium\Application\chrome.exe",
        ]
        found = [str(Path(r) / p) for r in roots if r for p in rel]
    elif sys.platform == "darwin":
        found = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    else:
        found = [
            shutil.which(n) or ""
            for n in (
                "google-chrome",
                "google-chrome-stable",
                "chromium",
                "chromium-browser",
                "microsoft-edge",
            )
        ]
    return [p for p in found if p]


def find_chromium(explicit: str | None = None) -> str:
    """An explicit path, JEV_BROWSER_EXECUTABLE, or an installed Chrome/Edge/Chromium."""
    choice = explicit or os.environ.get("JEV_BROWSER_EXECUTABLE")
    if choice:
        if Path(choice).is_file():
            return choice
        raise CDPError("browser executable not found")
    for path in _candidates():
        if Path(path).is_file():
            return path
    raise CDPError("No Chrome, Edge or Chromium found; set JEV_BROWSER_EXECUTABLE")


class LaunchedBrowser:
    """A private headless Chromium with a throwaway profile, closed and removed on exit."""

    def __init__(
        self,
        executable: str | None = None,
        headless: bool = True,
        timeout: float = 20,
        extra_args: list[str] | None = None,
    ):
        self.executable = find_chromium(executable)
        self.profile = tempfile.mkdtemp(prefix="jev-browser-")
        args = [
            self.executable,
            "--remote-debugging-port=0",
            f"--user-data-dir={self.profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-sync",
            "--window-size=1280,900",
            "about:blank",
        ]
        if headless:
            args.insert(1, "--headless=new")
        args[1:1] = list(extra_args or [])
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        self.process = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags
        )
        marker = Path(self.profile) / "DevToolsActivePort"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self.close()
                raise CDPError("browser exited during startup")
            if marker.is_file():
                lines = marker.read_text(encoding="utf-8").split()
                if len(lines) >= 2 and lines[0].isdigit():
                    self.port = int(lines[0])
                    self.ws_url = f"ws://127.0.0.1:{self.port}{lines[1]}"
                    return
            time.sleep(0.05)
        self.close()
        raise CDPError("browser did not expose DevTools in time")

    def close(self) -> None:
        process = getattr(self, "process", None)
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(5)
        for _ in range(20):
            try:
                shutil.rmtree(self.profile)
                break
            except FileNotFoundError:
                break
            except OSError:
                time.sleep(0.1)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
