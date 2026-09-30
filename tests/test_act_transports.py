"""Browser transports against fake local servers: Camofox REST and a scripted DevTools socket."""

import http.server
import json
import threading

import pytest

from jev_context.act import browser, cdp
from jev_context.act.browser import ActionFailed, CamofoxPage, CDPPage, StalePage
from tests.test_cdp import FakeDevTools, _frame, _read_frame

OBSERVED = {
    "url": "http://127.0.0.1:9/index.html",
    "title": "Fixture",
    "text": "Search",
    "scroll": {"y": 0},
    "actions": [
        {"id": "e1", "kind": "click", "label": "Go", "role": "button", "node": 1},
        {"id": "e2", "kind": "fill", "label": "Query", "role": "textbox", "node": 2, "value": ""},
        {
            "id": "e3",
            "kind": "click",
            "label": "Framed",
            "role": "button",
            "node": 3,
            "frame": True,
        },
        {"id": "scroll_down", "kind": "scroll", "label": "Scroll down", "delta": 500},
        {"id": "press_enter", "kind": "key", "key": "Enter", "label": "Press Enter"},
        {"id": "back", "kind": "back", "label": "Back"},
    ],
    "marker": ["m"],
    "page_key": ["k"],
    "guards": {"1": ["g1"], "2": ["g2"], "3": ["g3"]},
}


def op_of(expression):
    body = expression.rstrip()
    start = body.rfind(")({")
    if start < 0 or not body.endswith("})"):
        return {"raw": expression}
    return json.loads(body[start + 2 : -1])


def page_reply(request, state):
    op = request.get("op")
    if op == "observe":
        return json.loads(json.dumps(OBSERVED))
    if op == "marker":
        return state.get("marker", ["m"])
    if op == "guard":
        return [["k"], ["g%d" % request["node"]]]
    if op == "resolve":
        if state.get("covered"):
            return {"ok": False, "reason": "covered"}
        return {"ok": True, "x": 10, "y": 20, "selector": '[data-jev-act="a1"]'}
    if op == "readback":
        return {"value": state.get("typed", ""), "focused": True}
    if op == "settle":
        return True
    if op == "extract":
        return {"records": [{"id": "r1", "kind": "row", "text": "Product: X"}], "omitted": 0}
    raw = request.get("raw", "")
    if raw == "document.readyState":
        return "complete"
    if raw == "scrollY":
        state["scroll"] = state.get("scroll", 0) + 1
        return state["scroll"] if state["scroll"] > 1 else 0
    return None


# ---------------------------------------------------------------------------------------------
class FakeCamofox(http.server.BaseHTTPRequestHandler):
    state = {}
    calls = []

    def log_message(self, *args):
        pass

    def _body(self):
        size = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(size) or b"{}")

    def _send(self, payload, status=200):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = self._body()
        self.calls.append((self.path, body))
        if not body.get("userId"):
            return self._send({"error": "userId is required"}, 400)
        if self.path == "/tabs":
            return self._send({"tabId": "tab-1"})
        if self.path.endswith("/evaluate"):
            request = op_of(body["expression"])
            if request.get("op") == "boom":
                return self._send(
                    {"ok": False, "errorType": "js_error", "error": "unknown_operation"}
                )
            return self._send({"ok": True, "result": page_reply(request, self.state)})
        if self.path.endswith("/type"):
            self.state["typed"] = body["text"]
        return self._send({"ok": True})

    def do_DELETE(self):
        body = self._body()
        self.calls.append(("DELETE " + self.path, body))
        return self._send(
            {"ok": True} if body.get("userId") else {"error": "userId is required"},
            200 if body.get("userId") else 400,
        )


@pytest.fixture
def camofox():
    FakeCamofox.state = {}
    FakeCamofox.calls = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeCamofox)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_camofox_page_observes_executes_and_cleans_up(camofox):
    page = CamofoxPage("bench", url="http://127.0.0.1:9/index.html", base=camofox)
    state = page.observe()
    assert state["fingerprint"] and state["frame_actions_excluded"] == 1
    assert [a["id"] for a in state["actions"]][:2] == ["e1", "e2"]
    assert page.act(state["actions"][0], state) == {"executed": "e1"}
    assert page.act(state["actions"][1], state, text="red shoes") == {"executed": "e2"}
    assert page.act(next(a for a in state["actions"] if a["kind"] == "scroll"), state)["executed"]
    page.act(next(a for a in state["actions"] if a["kind"] == "key"), state)
    page.act(next(a for a in state["actions"] if a["kind"] == "back"), state)
    assert page.extract()["records"][0]["text"] == "Product: X"
    page.close()
    paths = [p for p, _ in FakeCamofox.calls]
    assert "/tabs" in paths and any(p.endswith("/click") for p in paths)
    assert any(p.endswith("/press") for p in paths) and any(p.endswith("/back") for p in paths)
    delete = next(b for p, b in FakeCamofox.calls if p.startswith("DELETE"))
    assert delete == {"userId": "camofox-bench"}


def test_camofox_rejects_covered_targets_and_bad_sessions(camofox):
    page = CamofoxPage("bench", url="http://127.0.0.1:9/", base=camofox)
    state = page.observe()
    FakeCamofox.state["covered"] = True
    with pytest.raises(StalePage, match="covered"):
        page.act(state["actions"][0], state)
    with pytest.raises(ValueError, match="rejected"):
        page.call({"op": "boom"})
    with pytest.raises(ValueError, match="fill requires"):
        FakeCamofox.state.pop("covered")
        page.act(state["actions"][1], state, text=None)
    with pytest.raises(ValueError):
        CamofoxPage("bad session!", url="http://x/", base=camofox)
    with pytest.raises(ValueError, match="loopback"):
        CamofoxPage("bench", url="http://x/", base="http://10.0.0.1:9377")
    with pytest.raises(ValueError, match="URL"):
        CamofoxPage("bench", base=camofox)


def test_stale_marker_blocks_scroll_and_stale_guard_blocks_click(camofox):
    page = CamofoxPage("bench", url="http://127.0.0.1:9/", base=camofox)
    state = page.observe()
    FakeCamofox.state["marker"] = ["changed"]
    with pytest.raises(StalePage):
        page.act(next(a for a in state["actions"] if a["kind"] == "scroll"), state)
    state["guards"]["1"] = ["different"]
    with pytest.raises(StalePage):
        page.act(state["actions"][0], state)


def test_unreachable_camofox_is_a_clean_error():
    with pytest.raises(RuntimeError, match="camofox_unavailable"):
        CamofoxPage("bench", url="http://127.0.0.1:9/", base="http://127.0.0.1:9")


# ---------------------------------------------------------------------------------------------
def devtools_handler(state):
    """Serve the CDP calls CDPPage makes; Runtime.evaluate answers from page_reply()."""

    def handler(server, conn):
        while True:
            try:
                fin, opcode, masked, data = _read_frame(conn)
            except (OSError, IndexError):
                return
            if opcode == 0x8 or not data:
                return
            message = json.loads(data)
            method = message["method"]
            server.seen.append(method)
            result = {}
            if method == "Target.createTarget":
                result = {"targetId": "T1"}
            elif method == "Target.getTargets":
                result = {"targetInfos": [{"targetId": "T1"}]}
            elif method == "Target.attachToTarget":
                result = {"sessionId": "S1"}
            elif method == "Runtime.evaluate":
                expression = message["params"]["expression"]
                if state.get("dialog_once"):
                    state.pop("dialog_once")
                    conn.sendall(
                        _frame(
                            0x1,
                            json.dumps(
                                {
                                    "method": "Page.javascriptDialogOpening",
                                    "sessionId": "S1",
                                    "params": {"type": "confirm", "message": "Sure?"},
                                }
                            ).encode(),
                        )
                    )
                if state.get("destroyed_once"):
                    state.pop("destroyed_once")
                    conn.sendall(
                        _frame(
                            0x1,
                            json.dumps(
                                {
                                    "id": message["id"],
                                    "error": {"message": "Execution context was destroyed."},
                                }
                            ).encode(),
                        )
                    )
                    continue
                value = page_reply(op_of(expression), state)
                result = {"result": {"value": value}}
            elif method == "Page.getNavigationHistory":
                result = {"currentIndex": 1, "entries": [{"id": 7}, {"id": 8}]}
            elif method == "Page.navigate":
                result = {"frameId": "F"}
            conn.sendall(_frame(0x1, json.dumps({"id": message["id"], "result": result}).encode()))

    return handler


def test_cdp_page_drives_a_scripted_devtools_session(monkeypatch):
    state = {"dialog_once": True}
    server = FakeDevTools(devtools_handler(state))
    monkeypatch.setattr(
        cdp, "browser_ws_url", lambda port: f"ws://127.0.0.1:{server.port}/devtools/browser/x"
    )
    page = CDPPage("http://127.0.0.1:9/index.html", port=9222)
    try:
        state_obs = page.observe()
        assert page.dialogs == [{"type": "confirm", "message": "Sure?"}]
        page.act(state_obs["actions"][0], state_obs)
        state["typed"] = "red shoes"
        assert page.act(state_obs["actions"][1], state_obs, text="red shoes") == {"executed": "e2"}
        assert page.act(next(a for a in state_obs["actions"] if a["kind"] == "scroll"), state_obs)[
            "scrolled"
        ]
        page.act(next(a for a in state_obs["actions"] if a["kind"] == "key"), state_obs)
        page.act(next(a for a in state_obs["actions"] if a["kind"] == "back"), state_obs)
        state["destroyed_once"] = True
        with pytest.raises(StalePage):
            page.evaluate("document.title")
        session = page.detach()
        assert session == {"cdp_port": 9222, "target_id": "T1"}
    finally:
        page.close()
    for method in (
        "Page.handleJavaScriptDialog",
        "Input.dispatchMouseEvent",
        "Input.insertText",
        "Input.dispatchKeyEvent",
        "Page.navigateToHistoryEntry",
        "Emulation.setFocusEmulationEnabled",
    ):
        assert method in server.seen


def test_cdp_page_attach_requires_a_known_target(monkeypatch):
    server = FakeDevTools(devtools_handler({}))
    monkeypatch.setattr(
        cdp, "browser_ws_url", lambda port: f"ws://127.0.0.1:{server.port}/devtools/browser/x"
    )
    with pytest.raises(cdp.CDPError, match="target not found"):
        CDPPage(port=9222, target_id="NOPE")


def test_select_failure_is_not_retried(monkeypatch):
    class Page(browser.Page):
        def evaluate(self, expression, await_promise=False):
            request = op_of(expression)
            if request.get("op") == "guard":
                return [["k"], ["g4"]]
            return {"ok": False, "reason": "target_changed"}

        def _execute(self, action, text):
            return self.resolve(action)

    action = {"id": "e4", "kind": "select", "node": 4, "value": "x"}
    with pytest.raises(ActionFailed):
        Page().act(action, {"page_key": ["k"], "guards": {"4": ["g4"]}})


def test_origin_normalization():
    assert browser.origin_of("https://Example.com:443/a?b") == "https://example.com"
    assert browser.origin_of("http://127.0.0.1:8765/x") == "http://127.0.0.1:8765"
    assert browser.origin_of("about:blank") == "about:"
