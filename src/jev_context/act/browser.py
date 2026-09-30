"""Browser transports for hosted execution: a DevTools (CDP) page and a Camofox tab.

Both transports run the same program-owned page script. Execution always resolves the target
from an observed node, re-checks visibility/enablement/occlusion, and never accepts a selector,
coordinate or script from the model.
"""

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import cdp

PAGE_JS = (Path(__file__).resolve().parent / "page.js").read_text(encoding="utf-8")
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class StalePage(ValueError):
    """The decision no longer refers to the observed page; observe again."""


class ActionFailed(RuntimeError):
    """An executed mutation could not be confirmed; do not blindly retry."""


def fingerprint(state):
    content = {k: state.get(k) for k in ("url", "text", "actions", "scroll")}
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def origin_of(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme in ("http", "https") and parts.hostname:
        default = {"http": 80, "https": 443}[parts.scheme]
        port = f":{parts.port}" if parts.port and parts.port != default else ""
        return f"{parts.scheme}://{parts.hostname}{port}"
    return parts.scheme + ":"


def script(request):
    return "(" + PAGE_JS + ")(" + json.dumps(request, ensure_ascii=False) + ")"


class Page:
    """Shared observation/execution logic; transports supply ``evaluate`` and raw input."""

    name = "page"
    supports_frames = True

    def evaluate(self, expression, await_promise=False):  # pragma: no cover - abstract
        raise NotImplementedError

    def call(self, request, await_promise=False):
        return self.evaluate(script(request), await_promise=await_promise)

    def observe(self, limit=250, scope=None, text_limit=6000):
        for attempt in range(10):
            try:
                info = self.call(
                    {"op": "observe", "limit": limit, "scope": scope, "text_limit": text_limit}
                )
            except StalePage:
                if attempt == 9:
                    raise
                time.sleep(0.05)
                continue
            if info is None:
                time.sleep(0.05)
                continue
            if info.get("scope_missing"):
                return info
            if not self.supports_frames:
                kept = [a for a in info["actions"] if not a.get("frame")]
                info["frame_actions_excluded"] = len(info["actions"]) - len(kept)
                info["actions"] = kept
            info["fingerprint"] = fingerprint(info)
            return info
        raise StalePage("Page did not settle")

    def fresh(self, page, action=None):
        if action is not None and action.get("kind") in ("click", "select", "fill"):
            current = self.call({"op": "guard", "node": action["node"]})
            return current == [page["page_key"], page["guards"].get(str(action["node"]))]
        return self.call({"op": "marker"}) == page["marker"]

    def settle(self, action):
        try:
            self.call({"op": "settle", "action": action}, await_promise=True)
        except (StalePage, cdp.CDPError, RuntimeError):
            pass

    def extract(self, scope=None, limit=500):
        return self.call({"op": "extract", "scope": scope, "limit": limit})

    def readback(self, node):
        return self.call({"op": "readback", "node": node})

    def resolve(self, action, tag=False):
        result = self.call({"op": "resolve", "action": action, "tag": tag})
        if not result or not result.get("ok"):
            reason = (result or {}).get("reason", "target_changed")
            if action["kind"] == "select":
                raise ActionFailed(f"select not applied: {reason}")
            raise StalePage(f"target {reason}")
        return result

    def act(self, action, page, text=None):
        """Execute one observed action. Returns an execution record for the archive."""
        kind = action["kind"]
        if kind in ("click", "select", "fill") and not self.fresh(page, action):
            raise StalePage("Page changed since this decision")
        if kind in ("scroll", "key", "back") and not self.fresh(page):
            raise StalePage("Page changed since this decision")
        if kind == "wait":
            time.sleep(0.1)
            return {"executed": action["id"]}
        if kind == "fill" and not isinstance(text, str):
            raise ValueError("fill requires program-supplied text")
        record = self._execute(action, text)
        return {"executed": action["id"], **record}

    def _execute(self, action, text):  # pragma: no cover - abstract
        raise NotImplementedError


class CDPPage(Page):
    """A page driven over a loopback DevTools WebSocket (Chrome, Edge, Chromium)."""

    name = "cdp"

    def __init__(
        self,
        url=None,
        *,
        ws_url=None,
        port=None,
        executable=None,
        headless=True,
        viewport=(1280, 900),
        dialogs="dismiss",
        target_id=None,
    ):
        self.launched = None
        self.port = port
        if not ws_url:
            if port:
                ws_url = cdp.browser_ws_url(port)
            else:
                self.launched = cdp.LaunchedBrowser(executable, headless=headless)
                ws_url = self.launched.ws_url
                self.port = self.launched.port
        self.conn = cdp.Connection(ws_url)
        self.dialogs = []
        self.dialog_policy = dialogs
        try:
            if target_id:
                known = {t["targetId"] for t in self.conn.call("Target.getTargets")["targetInfos"]}
                if target_id not in known:
                    raise cdp.CDPError("target not found")
                self.target = target_id
            else:
                self.target = self.conn.call(
                    "Target.createTarget", {"url": "about:blank", "background": True}
                )["targetId"]
            self.session = self.conn.call(
                "Target.attachToTarget", {"targetId": self.target, "flatten": True}
            )["sessionId"]
            self.conn.on("Page.javascriptDialogOpening", self._dialog)
            self.cmd("Page.enable")
            self.cmd("Runtime.enable")
            self.cmd(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": viewport[0],
                    "height": viewport[1],
                    "deviceScaleFactor": 1,
                    "mobile": False,
                },
            )
            # Keep animation frames running in a background tab without stealing focus.
            self.cmd("Emulation.setFocusEmulationEnabled", {"enabled": True})
            if url:
                self.navigate(url)
        except Exception:
            self.close()
            raise

    def _dialog(self, event):
        params = event.get("params", {})
        self.dialogs.append(
            {"type": params.get("type"), "message": (params.get("message") or "")[:300]}
        )
        accept = self.dialog_policy == "accept" and params.get("type") in ("alert", "beforeunload")
        self.conn.call(
            "Page.handleJavaScriptDialog", {"accept": accept}, session_id=event.get("sessionId")
        )

    def cmd(self, method, params=None, timeout=None):
        return self.conn.call(method, params, session_id=self.session, timeout=timeout)

    def evaluate(self, expression, await_promise=False):
        try:
            response = self.cmd(
                "Runtime.evaluate",
                {"expression": expression, "returnByValue": True, "awaitPromise": await_promise},
            )
        except cdp.CDPError as error:
            if "Execution context was destroyed" in str(error) or "Cannot find context" in str(
                error
            ):
                raise StalePage("Document changed during evaluation") from None
            raise
        if response.get("exceptionDetails"):
            detail = response["exceptionDetails"]
            text = json.dumps(detail.get("exception", {}).get("description", ""))[:200]
            if "unknown_operation" in text:
                raise ValueError("page script rejected the operation")
            raise StalePage("Document changed during evaluation")
        return response.get("result", {}).get("value")

    def navigate(self, url, timeout=20):
        result = self.cmd("Page.navigate", {"url": url})
        if result.get("errorText"):
            raise RuntimeError(f"navigation failed: {result['errorText']}")
        self.wait_ready(timeout)

    def wait_ready(self, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if self.evaluate("document.readyState") == "complete":
                    return True
            except StalePage:
                pass
            time.sleep(0.02)
        return False

    def mouse_click(self, x, y):
        for event in ("mouseMoved", "mousePressed", "mouseReleased"):
            params = {"type": event, "x": x, "y": y, "button": "left", "clickCount": 1}
            if event == "mouseMoved":
                params = {"type": event, "x": x, "y": y}
            self.cmd("Input.dispatchMouseEvent", params)

    def _execute(self, action, text):
        kind = action["kind"]
        if kind == "scroll":
            before = self.evaluate("scrollY")
            self.cmd(
                "Input.dispatchMouseEvent",
                {"type": "mouseWheel", "x": 400, "y": 400, "deltaX": 0, "deltaY": action["delta"]},
            )
            # Wheel scrolling can animate; wait until the offset settles before observing.
            deadline = time.monotonic() + 0.6
            last = before
            while time.monotonic() < deadline:
                time.sleep(0.03)
                current = self.evaluate("scrollY")
                if current != before and current == last:
                    break
                last = current
            return {"scrolled": last != before}
        if kind == "key":
            for kind_ in ("keyDown", "keyUp"):
                params = {
                    "type": kind_,
                    "key": "Enter",
                    "code": "Enter",
                    "windowsVirtualKeyCode": 13,
                }
                if kind_ == "keyDown":
                    params["text"] = "\r"
                self.cmd("Input.dispatchKeyEvent", params)
            return {}
        if kind == "back":
            history = self.cmd("Page.getNavigationHistory")
            index = history.get("currentIndex", 0)
            if index <= 0:
                raise StalePage("no history entry")
            self.cmd(
                "Page.navigateToHistoryEntry", {"entryId": history["entries"][index - 1]["id"]}
            )
            self.wait_ready(10)
            return {}
        target = self.resolve(action)
        if kind == "select":
            return {"applied": True}
        self.mouse_click(target["x"], target["y"])
        if kind == "fill":
            modifier = 4 if sys.platform == "darwin" else 2
            self.cmd(
                "Input.dispatchKeyEvent",
                {
                    "type": "keyDown",
                    "key": "a",
                    "code": "KeyA",
                    "modifiers": modifier,
                    "commands": ["selectAll"],
                },
            )
            self.cmd(
                "Input.dispatchKeyEvent",
                {"type": "keyUp", "key": "a", "code": "KeyA", "modifiers": modifier},
            )
            self.cmd("Input.insertText", {"text": text})
            back = self.readback(action["node"]) or {}
            if not action.get("sensitive") and back.get("value") not in (None, text):
                return {"readback_mismatch": True}
        return {}

    def screenshot(self):
        return self.cmd("Page.captureScreenshot", {"format": "jpeg", "quality": 70})["data"]

    def detach(self):
        """Leave the tab (and a launched browser) running for a later run to resume."""
        session = {"cdp_port": self.port, "target_id": self.target}
        if self.launched:
            session["profile"] = self.launched.profile
            self.launched = None  # ownership passes to the caller
        conn = getattr(self, "conn", None)
        if conn:
            conn.close()
        self.target = None
        return session

    def close(self, close_browser=False):
        conn = getattr(self, "conn", None)
        if conn and getattr(self, "target", None):
            try:
                conn.call("Target.closeTarget", {"targetId": self.target}, timeout=5)
            except cdp.CDPError:
                pass
        if conn and close_browser and not self.launched:
            try:
                conn.call("Browser.close", timeout=5)
            except cdp.CDPError:
                pass
        if conn:
            conn.close()
        if self.launched:
            self.launched.close()
            self.launched = None


class CamofoxPage(Page):
    """A tab in a local Camofox server (anti-detection Firefox) driven over its REST API."""

    name = "camofox"
    supports_frames = False

    def __init__(self, session, tab=None, url=None, base=None):
        import re

        if not re.fullmatch(r"[A-Za-z0-9._-]+", session):
            raise ValueError("Invalid named browser session")
        self.base = (base or os.environ.get("JEV_CAMOFOX_URL") or "http://localhost:9377").rstrip(
            "/"
        )
        if (urllib.parse.urlsplit(self.base).hostname or "") not in LOOPBACK_HOSTS:
            raise ValueError("Camofox endpoint must be loopback")
        self.user = "camofox-" + session
        self.owned = tab is None
        self.dialogs = []
        if tab is None:
            if not url:
                raise ValueError("A new Camofox tab needs a URL")
            tab = self.api(
                "POST", "/tabs", {"userId": self.user, "sessionKey": session, "url": url}
            )["tabId"]
        self.tab = tab
        if url and not self.owned:
            self.navigate(url)

    def api(self, method, path, body=None, timeout=60):
        headers = {"Content-Type": "application/json"}
        key = os.environ.get("CAMOFOX_API_KEY")
        if key:
            headers["Authorization"] = "Bearer " + key
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"camofox_http_{error.code}") from None
        except OSError:
            raise RuntimeError("camofox_unavailable") from None

    def evaluate(self, expression, await_promise=False):
        result = self.api(
            "POST",
            f"/tabs/{urllib.parse.quote(self.tab, safe='')}/evaluate",
            {"userId": self.user, "expression": expression},
        )
        if result.get("ok") is False:
            if result.get("errorType") == "js_error" and "unknown_operation" in str(
                result.get("error")
            ):
                raise ValueError("page script rejected the operation")
            raise StalePage("Document changed during evaluation")
        return result.get("result")

    def _tab(self, suffix, body=None):
        return self.api(
            "POST",
            f"/tabs/{urllib.parse.quote(self.tab, safe='')}/{suffix}",
            {"userId": self.user, **(body or {})},
        )

    def navigate(self, url, timeout=20):
        self._tab("navigate", {"url": url})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if self.evaluate("document.readyState") == "complete":
                    return True
            except StalePage:
                pass
            time.sleep(0.05)
        return False

    def _execute(self, action, text):
        kind = action["kind"]
        if kind == "scroll":
            self.evaluate(f"window.scrollBy(0, {int(action['delta'])})")
            return {}
        if kind == "key":
            self._tab("press", {"key": "Enter"})
            return {}
        if kind == "back":
            self._tab("back")
            return {}
        target = self.resolve(action, tag=True)
        if kind == "select":
            return {"applied": True}
        if kind == "click":
            self._tab("click", {"selector": target["selector"]})
            return {}
        self._tab("type", {"selector": target["selector"], "text": text})
        back = self.readback(action["node"]) or {}
        if not action.get("sensitive") and back.get("value") not in (None, text):
            return {"readback_mismatch": True}
        return {}

    def close(self):
        if self.owned and getattr(self, "tab", None):
            try:
                self.api(
                    "DELETE",
                    f"/tabs/{urllib.parse.quote(self.tab, safe='')}",
                    {"userId": self.user},
                    timeout=10,
                )
            except RuntimeError:
                pass
            self.tab = None
